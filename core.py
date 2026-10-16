"""Cuentas Coarcun - lógica del programa (sin interfaz)."""
import difflib
import hashlib
import hmac
import io
import os
import re
import secrets
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import date, datetime, time

import pandas as pd

DB_PATH = os.environ.get("COARCUN_DB", "cuentas_coarcun.db")
CODIGO_FILE = os.environ.get("COARCUN_CODE_FILE", "codigo_admin.txt")

RESIDENCIAS = ["Fusagasugá", "Bogotá", "La Mesa", "Facatativá",
               "Girardot", "Soacha", "Chía", "Tocancipá"]
# Los 116 municipios de Cundinamarca (más Bogotá, que no es municipio pero es sede frecuente).
MUNICIPIOS_CUNDINAMARCA = [
    "Agua de Dios", "Albán", "Anapoima", "Anolaima", "Apulo", "Arbeláez", "Beltrán", "Bituima",
    "Bojacá", "Cabrera", "Cachipay", "Cajicá", "Caparrapí", "Cáqueza", "Carmen de Carupa",
    "Chaguaní", "Chía", "Chipaque", "Choachí", "Chocontá", "Cogua", "Cota", "Cucunubá",
    "El Colegio", "El Peñón", "El Rosal", "Facatativá", "Fómeque", "Fosca", "Funza", "Fúquene",
    "Fusagasugá", "Gachalá", "Gachancipá", "Gachetá", "Gama", "Girardot", "Granada", "Guachetá",
    "Guaduas", "Guasca", "Guataquí", "Guatavita", "Guayabal de Síquima", "Guayabetal",
    "Gutiérrez", "Jerusalén", "Junín", "La Calera", "La Mesa", "La Palma", "La Peña", "La Vega",
    "Lenguazaque", "Machetá", "Madrid", "Manta", "Medina", "Mosquera", "Nariño", "Nemocón",
    "Nilo", "Nimaima", "Nocaima", "Pacho", "Paime", "Pandi", "Paratebueno", "Pasca",
    "Puerto Salgar", "Pulí", "Quebradanegra", "Quetame", "Quipile", "Ricaurte",
    "San Antonio del Tequendama", "San Bernardo", "San Cayetano", "San Francisco",
    "San Juan de Rioseco", "Sasaima", "Sesquilé", "Sibaté", "Silvania", "Simijaca", "Soacha",
    "Sopó", "Subachoque", "Suesca", "Supatá", "Susa", "Sutatausa", "Tabio", "Tausa", "Tena",
    "Tenjo", "Tibacuy", "Tibirita", "Tocaima", "Tocancipá", "Topaipí", "Ubalá", "Ubaque", "Une",
    "Útica", "Vergara", "Venecia", "Vianí", "Villa de San Diego de Ubaté", "Villagómez", "Villapinzón",
    "Villeta", "Viotá", "Yacopí", "Zipacón", "Zipaquirá", "Bogotá",
]
ROL_CENTRAL, ROL_ASISTENTE, ROL_EMERGENTE = "Arbitro", "Asistente", "Emergente"
ROLES_COBRABLES = (ROL_CENTRAL, ROL_ASISTENTE, ROL_EMERGENTE)
TODOS = "Todos los torneos"
TIPOS_CARGO = ("Multa",)  # las mensualidades se cargan desde Excel

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


# ---------------------------------------------------------------- utilidades
def norm(s) -> str:
    """Minúsculas, sin tildes y sin espacios repetidos (para comparar nombres)."""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().lower()


def limpiar(s) -> str:
    return re.sub(r"\s+", " ", str(s)).strip()


def fmt(n) -> str:
    return f"{n:,.0f}".replace(",", ".")


def fecha_bonita(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day:02d} de {MESES[d.month - 1].capitalize()}"


def parse_fecha(v):
    """Acepta fechas reales o textos como 'jueves, octubre 15, 2026'."""
    if hasattr(v, "date") and not isinstance(v, str):
        return v.date().isoformat()
    m = re.search(r"([A-Za-zÁÉÍÓÚáéíóúñÑ]+)\s+(\d{1,2}),?\s+(\d{4})", str(v))
    if m and norm(m.group(1)) in [norm(x) for x in MESES]:
        mes = [norm(x) for x in MESES].index(norm(m.group(1))) + 1
        return date(int(m.group(3)), mes, int(m.group(2))).isoformat()
    try:
        return pd.to_datetime(str(v), dayfirst=True).date().isoformat()
    except Exception:
        return None


def parse_hora(v) -> str:
    """Redondea al minuto (el Excel trae basura como 10:59:59.971)."""
    if isinstance(v, time):
        seg = v.hour * 3600 + v.minute * 60 + v.second + v.microsecond / 1e6
        mins = round(seg / 60)
        return f"{(mins // 60) % 24:02d}:{mins % 60:02d}"
    return "" if v is None or pd.isna(v) else str(v)


def normalizar_rol(v) -> str:
    n = norm(v)
    return {"arbitro": ROL_CENTRAL, "asistente": ROL_ASISTENTE}.get(n, limpiar(v).capitalize())


def es_cc(v) -> bool:
    """True si el cobro del servicio es 'CC' (también acepta 'C.C.' o ' cc ')."""
    return re.sub(r"[^a-z]", "", norm(v or "")) == "cc"


def sql_cc(col="cobro") -> str:
    """Misma condición en SQL (SQLite y Postgres)."""
    return f"UPPER(REPLACE(REPLACE(TRIM(COALESCE({col}, '')), '.', ''), ' ', '')) = 'CC'"


def normalizar_torneo(v) -> str:
    return limpiar(v).rstrip(". ")


# ------------------------------------------------------------- base de datos
_cfg = {}


def _secreto(nombre):
    """Lee un valor de la variable de entorno o de los Secrets de Streamlit."""
    if nombre not in _cfg:
        v = os.environ.get(nombre)
        if not v:
            try:
                import streamlit as st
                v = st.secrets.get(nombre)
            except Exception:
                v = None
        _cfg[nombre] = v or None
    return _cfg[nombre]


def usa_postgres() -> bool:
    """True si hay DATABASE_URL (nube). Si no, se usa el archivo SQLite local."""
    return bool(_secreto("DATABASE_URL"))


def _errores_integridad():
    errs = (sqlite3.IntegrityError,)
    if usa_postgres():
        import psycopg2
        errs += (psycopg2.IntegrityError,)
    return errs


class _Conn:
    """Misma interfaz para SQLite y Postgres: execute(sql_con_?, params) -> cursor."""

    def __init__(self, raw, pg):
        self.raw, self.pg = raw, pg

    def execute(self, sql, params=()):
        if self.pg:
            cur = self.raw.cursor()
            cur.execute(sql.replace("?", "%s"), tuple(params))
            return cur
        return self.raw.execute(sql, tuple(params))


def _conectar():
    if usa_postgres():
        import psycopg2
        from psycopg2.extras import RealDictCursor
        raw = psycopg2.connect(_secreto("DATABASE_URL"), cursor_factory=RealDictCursor, connect_timeout=20)
        return _Conn(raw, True)
    raw = sqlite3.connect(DB_PATH)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA foreign_keys = ON")
    return _Conn(raw, False)


@contextmanager
def db():
    c = _conectar()
    try:
        yield c
        c.raw.commit()
    finally:
        c.raw.close()


def consulta_df(c, sql, params=()):
    """Ejecuta una consulta y devuelve un DataFrame (funciona igual en SQLite y Postgres)."""
    cur = c.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return pd.DataFrame([tuple(r[k] for k in cols) for r in cur.fetchall()], columns=cols)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS arbitros(
    id {PK}, nombre TEXT NOT NULL,
    nombre_norm TEXT UNIQUE NOT NULL, residencia TEXT);
CREATE TABLE IF NOT EXISTS usuarios(
    id {PK}, nombre TEXT NOT NULL,
    nombre_norm TEXT UNIQUE NOT NULL, rol TEXT NOT NULL,
    arbitro_id INTEGER UNIQUE REFERENCES arbitros(id),
    pass_hash TEXT NOT NULL, salt TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS torneos(
    nombre TEXT PRIMARY KEY, paga_pasaje INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS precios(
    torneo TEXT, categoria TEXT, rol TEXT, valor {REAL} NOT NULL,
    PRIMARY KEY(torneo, categoria, rol));
CREATE TABLE IF NOT EXISTS pasajes(
    residencia TEXT, ciudad TEXT, valor {REAL} NOT NULL,
    PRIMARY KEY(residencia, ciudad));
CREATE TABLE IF NOT EXISTS pasaje_unico(
    torneo TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS pasajes_torneo(
    torneo TEXT, ciudad TEXT, valor {REAL} NOT NULL,
    PRIMARY KEY(torneo, ciudad));
CREATE TABLE IF NOT EXISTS servicios(
    id {PK}, uid TEXT UNIQUE NOT NULL,
    fecha TEXT NOT NULL, hora TEXT, torneo TEXT NOT NULL, ciudad TEXT,
    campo TEXT, categoria TEXT NOT NULL,
    arbitro_id INTEGER NOT NULL REFERENCES arbitros(id),
    partido TEXT, rol TEXT NOT NULL, fase TEXT, cobro TEXT,
    tipo_partido TEXT, archivo TEXT);
CREATE INDEX IF NOT EXISTS ix_serv ON servicios(arbitro_id, fecha);
CREATE TABLE IF NOT EXISTS cargos(
    id {PK}, arbitro_id INTEGER NOT NULL REFERENCES arbitros(id),
    tipo TEXT NOT NULL, concepto TEXT, fecha TEXT NOT NULL,
    valor {REAL} NOT NULL, saldado INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS alias_arbitros(
    alias_norm TEXT PRIMARY KEY, arbitro_id INTEGER NOT NULL REFERENCES arbitros(id));
CREATE TABLE IF NOT EXISTS arbitros_distintos(
    a_norm TEXT NOT NULL, b_norm TEXT NOT NULL, PRIMARY KEY(a_norm, b_norm));
CREATE TABLE IF NOT EXISTS alias_torneos(
    alias_norm TEXT PRIMARY KEY, torneo TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS torneos_distintos(
    a_norm TEXT NOT NULL, b_norm TEXT NOT NULL, PRIMARY KEY(a_norm, b_norm));
CREATE TABLE IF NOT EXISTS mensualidades(
    id {PK}, arbitro_id INTEGER NOT NULL REFERENCES arbitros(id),
    mes TEXT NOT NULL, valor {REAL} NOT NULL, saldado INTEGER NOT NULL DEFAULT 0,
    abonado {REAL} NOT NULL DEFAULT 0,
    UNIQUE(arbitro_id, mes));
"""
_init_hecho = set()


def init_db():
    """Crea las tablas si no existen (una sola vez por ejecución del programa)."""
    destino = _secreto("DATABASE_URL") or DB_PATH
    if destino in _init_hecho:
        return
    pg = usa_postgres()
    esquema = _SCHEMA.format(PK="SERIAL PRIMARY KEY" if pg else "INTEGER PRIMARY KEY",
                             REAL="DOUBLE PRECISION" if pg else "REAL")
    with db() as c:
        for stmt in esquema.split(";"):
            if stmt.strip():
                c.execute(stmt)
        # bases creadas antes de los abonos: agregar la columna
        if pg:
            c.execute("ALTER TABLE mensualidades ADD COLUMN IF NOT EXISTS abonado DOUBLE PRECISION NOT NULL DEFAULT 0")
        elif "abonado" not in [r["name"] for r in c.execute("PRAGMA table_info(mensualidades)")]:
            c.execute("ALTER TABLE mensualidades ADD COLUMN abonado REAL NOT NULL DEFAULT 0")
    _init_hecho.add(destino)


# ------------------------------------------------------------------ usuarios
def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()


def codigo_admin():
    """Código secreto para crear administradores.
    Nube: se define en los Secrets (COARCUN_ADMIN_CODE). Local: variable de entorno o archivo."""
    env = _secreto("COARCUN_ADMIN_CODE")
    if env:
        return env
    if usa_postgres():
        return None  # en la nube un archivo se borraría; el código debe estar en los Secrets
    if not os.path.exists(CODIGO_FILE):
        with open(CODIGO_FILE, "w") as f:
            f.write(secrets.token_urlsafe(8))
    return open(CODIGO_FILE).read().strip()


def verificar_codigo_admin(codigo) -> bool:
    real = codigo_admin()
    return bool(real) and hmac.compare_digest(str(codigo).encode(), real.encode())


def crear_usuario(nombre, password, rol, arbitro_id=None):
    if len(password) < 6:
        raise ValueError("La contraseña debe tener al menos 6 caracteres.")
    salt = secrets.token_hex(16)
    try:
        with db() as c:
            c.execute("INSERT INTO usuarios(nombre,nombre_norm,rol,arbitro_id,pass_hash,salt)"
                      " VALUES(?,?,?,?,?,?)",
                      (limpiar(nombre), norm(nombre), rol, arbitro_id, _hash(password, salt), salt))
    except _errores_integridad():
        raise ValueError("Ese nombre ya tiene una cuenta.")


def cambiar_password(usuario_id, password):
    if len(password) < 6:
        raise ValueError("La contraseña debe tener al menos 6 caracteres.")
    salt = secrets.token_hex(16)
    with db() as c:
        c.execute("UPDATE usuarios SET pass_hash=?, salt=? WHERE id=?",
                  (_hash(password, salt), salt, usuario_id))


def autenticar(nombre, password):
    with db() as c:
        u = c.execute("SELECT * FROM usuarios WHERE nombre_norm=?", (norm(nombre),)).fetchone()
    if u and hmac.compare_digest(u["pass_hash"], _hash(password, u["salt"])):
        return {"id": u["id"], "nombre": u["nombre"], "rol": u["rol"], "arbitro_id": u["arbitro_id"]}
    return None


def hay_administradores() -> bool:
    with db() as c:
        return c.execute("SELECT 1 FROM usuarios WHERE rol='admin'").fetchone() is not None


def arbitros_sin_cuenta():
    with db() as c:
        return [dict(r) for r in c.execute(
            "SELECT a.* FROM arbitros a LEFT JOIN usuarios u ON u.arbitro_id=a.id "
            "WHERE u.id IS NULL ORDER BY a.nombre")]


def registrar_arbitro(arbitro_id, password, residencia):
    with db() as c:
        a = c.execute("SELECT nombre FROM arbitros WHERE id=?", (arbitro_id,)).fetchone()
    crear_usuario(a["nombre"], password, "arbitro", arbitro_id)  # falla si ya tiene cuenta
    actualizar_residencia(arbitro_id, residencia)


def sugerir_nombres(nombre):
    """Árbitros sin cuenta cuyo nombre se parece al escrito (incluye nombres incompletos)."""
    n = norm(nombre)
    tokens = set(n.split())
    out = []
    for a in arbitros_sin_cuenta():
        cand = set(a["nombre_norm"].split())
        if (tokens and tokens <= cand) or difflib.SequenceMatcher(None, n, a["nombre_norm"]).ratio() >= 0.8:
            out.append(a["nombre"])
    return out[:5]


def registrar_arbitro_por_nombre(nombre, password, residencia, crear_si_no_existe=False):
    """El árbitro escribe su nombre. Si coincide con uno de las designaciones, se enlaza.
    Devuelve ('enlazado' | 'nuevo'). Lanza ValueError con un mensaje claro si no se puede."""
    nombre = limpiar(nombre)
    n = norm(nombre)
    if len(n.split()) < 2:
        raise ValueError("Escribe tu nombre completo (nombres y apellidos).")
    with db() as c:
        a = c.execute("SELECT id FROM arbitros WHERE nombre_norm=?", (n,)).fetchone()
        if not a:  # tal vez escribió una variante de su nombre que ya se unió a otra
            a = c.execute("SELECT arbitro_id AS id FROM alias_arbitros WHERE alias_norm=?", (n,)).fetchone()
    if a:
        registrar_arbitro(a["id"], password, residencia)  # lanza error si ya tiene cuenta
        return "enlazado"
    if not crear_si_no_existe:
        raise LookupError("No encontré ese nombre en las designaciones.")
    agregar_arbitro(nombre, residencia)
    with db() as c:
        aid = c.execute("SELECT id FROM arbitros WHERE nombre_norm=?", (n,)).fetchone()["id"]
    registrar_arbitro(aid, password, residencia)
    return "nuevo"


def _claves_de_servicios(c, donde, params, torneo=None, ignorar_arbitro=False):
    """{clave: [ids]} de los servicios que cumplen 'donde' (para comparar antes y después de unir)."""
    out = {}
    for r in c.execute("SELECT id,fecha,hora,torneo,ciudad,campo,categoria,arbitro_id,partido,rol,fase,cobro,tipo_partido "
                       "FROM servicios WHERE " + donde + " ORDER BY id", params):
        k = _clave_servicio(r["fecha"], r["hora"], torneo or r["torneo"], r["ciudad"], r["campo"], r["categoria"],
                            0 if ignorar_arbitro else r["arbitro_id"], r["partido"], r["rol"], r["fase"], r["cobro"], r["tipo_partido"])
        out.setdefault(k, []).append(r["id"])
    return out


def _quitar_repetidos_al_unir(c, de_destino, de_origen) -> int:
    """Si el mismo servicio estaba cargado con los dos nombres, queda una sola vez; pero si un nombre ya
    traía filas idénticas legítimas (ej. dos puestos de asistente), se respetan."""
    quitados = 0
    for k, ids_o in de_origen.items():
        n_d = len(de_destino.get(k, []))
        if not n_d:
            continue
        dejar = max(0, max(n_d, len(ids_o)) - n_d)
        for sid in ids_o[dejar:]:
            c.execute("DELETE FROM servicios WHERE id=?", (sid,))
            quitados += 1
    return quitados


def _tokens_contenidos(x, y) -> bool:
    """True si todas las palabras del nombre más corto (mínimo 2) aparecen en el más largo,
    tolerando una letra mal escrita. Ej.: 'felipe figueredo' dentro de 'andres felipe figueredo'."""
    tx, ty = x.split(), y.split()
    ch, gr = (tx, ty) if len(tx) <= len(ty) else (ty, tx)
    if len(ch) < 2 or set(ch) == set(gr):
        return False

    def aparece(t):
        return any(t == u or (len(t) >= 4 and len(u) >= 4 and difflib.SequenceMatcher(None, t, u).ratio() >= 0.85)
                   for u in gr)
    return all(aparece(t) for t in ch)


def _nombres_parecidos(x, y, umbral) -> bool:
    return _tokens_contenidos(x, y) or difflib.SequenceMatcher(None, x, y).ratio() >= umbral


def posibles_duplicados(umbral=0.88):
    """Pares de árbitros que podrían ser la misma persona: nombres casi iguales, o uno más completo que
    otro (Felipe Figueredo / Andrés Felipe Figueredo Castiblanco). También compara con los nombres
    que ya se unieron antes (alias). Excluye los pares que ya se marcaron como personas distintas."""
    with db() as c:
        arbs = [(r["id"], r["nombre"], r["nombre_norm"]) for r in c.execute(
            "SELECT id,nombre,nombre_norm FROM arbitros ORDER BY id")]
        distintos = {(r["a_norm"], r["b_norm"]) for r in c.execute("SELECT a_norm,b_norm FROM arbitros_distintos")}
        n_serv = {r["arbitro_id"]: r["n"] for r in c.execute(
            "SELECT arbitro_id, COUNT(*) AS n FROM servicios GROUP BY arbitro_id")}
        con_cuenta = {r["arbitro_id"] for r in c.execute(
            "SELECT arbitro_id FROM usuarios WHERE arbitro_id IS NOT NULL")}
        alias = {}
        for r in c.execute("SELECT alias_norm, arbitro_id FROM alias_arbitros"):
            alias.setdefault(r["arbitro_id"], []).append(r["alias_norm"])
    nombres = {a[0]: [a[2]] + alias.get(a[0], []) for a in arbs}
    out = []
    for i in range(len(arbs)):
        for j in range(i + 1, len(arbs)):
            a, b = arbs[i], arbs[j]
            if tuple(sorted((a[2], b[2]))) in distintos:
                continue
            if not any(_nombres_parecidos(x, y, umbral) for x in nombres[a[0]] for y in nombres[b[0]]):
                continue
            # sugerencia: el nombre más completo (más palabras, luego más letras)
            completo = max((a, b), key=lambda t: (len(t[2].split()), len(t[2])))[0]
            out.append({"a_id": a[0], "a_nombre": a[1], "a_servicios": n_serv.get(a[0], 0), "a_cuenta": a[0] in con_cuenta,
                        "b_id": b[0], "b_nombre": b[1], "b_servicios": n_serv.get(b[0], 0), "b_cuenta": b[0] in con_cuenta,
                        "sugerido": completo})
    return out


def marcar_distintos(id1, id2):
    """Registra que son personas diferentes para no volver a preguntar."""
    with db() as c:
        n1 = c.execute("SELECT nombre_norm FROM arbitros WHERE id=?", (id1,)).fetchone()
        n2 = c.execute("SELECT nombre_norm FROM arbitros WHERE id=?", (id2,)).fetchone()
        if n1 and n2:
            a, b = sorted((n1["nombre_norm"], n2["nombre_norm"]))
            c.execute("INSERT INTO arbitros_distintos(a_norm,b_norm) VALUES(?,?) ON CONFLICT DO NOTHING", (a, b))


def unir_arbitros(conservar_id, eliminar_id) -> dict:
    """Pasa todo lo del árbitro 'eliminar' al árbitro 'conservar' y borra el duplicado.
    El nombre eliminado queda como alias: en los próximos Excel se asigna solo al que se conservó."""
    if conservar_id == eliminar_id:
        raise ValueError("Elige dos árbitros distintos.")
    res = {"servicios": 0, "servicios_repetidos": 0, "mensualidades_descartadas": 0}
    with db() as c:
        keep = c.execute("SELECT * FROM arbitros WHERE id=?", (conservar_id,)).fetchone()
        elim = c.execute("SELECT * FROM arbitros WHERE id=?", (eliminar_id,)).fetchone()
        if not keep or not elim:
            raise ValueError("Uno de los árbitros ya no existe. Recarga la página.")
        cuentas = [r["arbitro_id"] for r in c.execute(
            "SELECT arbitro_id FROM usuarios WHERE arbitro_id IN (?,?)", (conservar_id, eliminar_id))]
        if len(cuentas) == 2:
            raise ValueError("Los dos ya tienen una cuenta creada, así que no se pueden unir automáticamente.")
        res["servicios"] = c.execute("SELECT COUNT(*) AS n FROM servicios WHERE arbitro_id=?", (eliminar_id,)).fetchone()["n"]
        k_dest = _claves_de_servicios(c, "arbitro_id=?", (conservar_id,), ignorar_arbitro=True)
        k_orig = _claves_de_servicios(c, "arbitro_id=?", (eliminar_id,), ignorar_arbitro=True)
        c.execute("UPDATE servicios SET arbitro_id=? WHERE arbitro_id=?", (conservar_id, eliminar_id))
        res["servicios_repetidos"] = _quitar_repetidos_al_unir(c, k_dest, k_orig)
        c.execute("UPDATE cargos SET arbitro_id=? WHERE arbitro_id=?", (conservar_id, eliminar_id))
        for m in list(c.execute("SELECT id, mes FROM mensualidades WHERE arbitro_id=?", (eliminar_id,))):
            if c.execute("SELECT 1 FROM mensualidades WHERE arbitro_id=? AND mes=?", (conservar_id, m["mes"])).fetchone():
                c.execute("DELETE FROM mensualidades WHERE id=?", (m["id"],))
                res["mensualidades_descartadas"] += 1
            else:
                c.execute("UPDATE mensualidades SET arbitro_id=? WHERE id=?", (conservar_id, m["id"]))
        if cuentas and cuentas[0] == eliminar_id:
            c.execute("UPDATE usuarios SET arbitro_id=? WHERE arbitro_id=?", (conservar_id, eliminar_id))
        if not keep["residencia"] and elim["residencia"]:
            c.execute("UPDATE arbitros SET residencia=? WHERE id=?", (elim["residencia"], conservar_id))
        c.execute("UPDATE alias_arbitros SET arbitro_id=? WHERE arbitro_id=?", (conservar_id, eliminar_id))
        c.execute("INSERT INTO alias_arbitros(alias_norm,arbitro_id) VALUES(?,?) "
                  "ON CONFLICT(alias_norm) DO UPDATE SET arbitro_id=excluded.arbitro_id",
                  (elim["nombre_norm"], conservar_id))
        c.execute("DELETE FROM arbitros WHERE id=?", (eliminar_id,))
    res["conservado"], res["eliminado"] = keep["nombre"], elim["nombre"]
    return res


def _sin_anio(x) -> str:
    return " ".join(re.sub(r"\b(19|20)\d{2}\b", "", x).split())


def _torneos_parecidos(x, y, umbral=0.88) -> bool:
    """Mismo nombre salvo el año, uno contenido en el otro, o casi igual (letra mal escrita)."""
    if x == y:
        return False
    sx, sy = _sin_anio(x), _sin_anio(y)
    if sx and sx == sy:
        return True
    return _tokens_contenidos(x, y) or difflib.SequenceMatcher(None, x, y).ratio() >= umbral


def torneos_posibles_duplicados():
    """Pares de torneos que podrían ser el mismo (Copa Santa Fe / Copa Santa Fe 2026)."""
    with db() as c:
        nombres = [r["nombre"] for r in c.execute("SELECT nombre FROM torneos ORDER BY nombre")]
        distintos = {(r["a_norm"], r["b_norm"]) for r in c.execute("SELECT a_norm,b_norm FROM torneos_distintos")}
        n_serv = {r["torneo"]: r["n"] for r in c.execute("SELECT torneo, COUNT(*) AS n FROM servicios GROUP BY torneo")}
        alias = {}
        for r in c.execute("SELECT alias_norm, torneo FROM alias_torneos"):
            alias.setdefault(r["torneo"], []).append(r["alias_norm"])
    out = []
    for i in range(len(nombres)):
        for j in range(i + 1, len(nombres)):
            a, b = nombres[i], nombres[j]
            if tuple(sorted((norm(a), norm(b)))) in distintos:
                continue
            if any(_torneos_parecidos(x, y) for x in [norm(a)] + alias.get(a, []) for y in [norm(b)] + alias.get(b, [])):
                out.append({"a": a, "a_servicios": n_serv.get(a, 0), "b": b, "b_servicios": n_serv.get(b, 0)})
    return out


def marcar_torneos_distintos(a, b):
    x, y = sorted((norm(a), norm(b)))
    with db() as c:
        c.execute("INSERT INTO torneos_distintos(a_norm,b_norm) VALUES(?,?) ON CONFLICT DO NOTHING", (x, y))


def unir_torneos(conservar, eliminar) -> dict:
    """Pasa servicios, precios y pasajes del torneo 'eliminar' al torneo 'conservar'.
    El nombre eliminado queda como alias: en los próximos Excel se asigna solo al que se conservó."""
    if conservar == eliminar:
        raise ValueError("Elige dos torneos distintos.")
    res = {"servicios": 0, "servicios_repetidos": 0, "precios_descartados": 0}
    with db() as c:
        modos = _modos_pasaje(c)
        if conservar not in modos or eliminar not in modos:
            raise ValueError("Uno de los torneos ya no existe. Recarga la página.")
        res["servicios"] = c.execute("SELECT COUNT(*) AS n FROM servicios WHERE torneo=?", (eliminar,)).fetchone()["n"]
        k_dest = _claves_de_servicios(c, "torneo=?", (conservar,), torneo=conservar)
        k_orig = _claves_de_servicios(c, "torneo=?", (eliminar,), torneo=conservar)
        c.execute("UPDATE servicios SET torneo=? WHERE torneo=?", (conservar, eliminar))
        res["servicios_repetidos"] = _quitar_repetidos_al_unir(c, k_dest, k_orig)
        for r in list(c.execute("SELECT categoria, rol, valor FROM precios WHERE torneo=?", (eliminar,))):
            if c.execute("SELECT 1 FROM precios WHERE torneo=? AND categoria=? AND rol=?",
                         (conservar, r["categoria"], r["rol"])).fetchone():
                res["precios_descartados"] += 1  # ya tenía precio: se respeta el del torneo que se conserva
            else:
                c.execute("INSERT INTO precios(torneo,categoria,rol,valor) VALUES(?,?,?,?)",
                          (conservar, r["categoria"], r["rol"], r["valor"]))
        for r in list(c.execute("SELECT ciudad, valor FROM pasajes_torneo WHERE torneo=?", (eliminar,))):
            if not c.execute("SELECT 1 FROM pasajes_torneo WHERE torneo=? AND ciudad=?", (conservar, r["ciudad"])).fetchone():
                c.execute("INSERT INTO pasajes_torneo(torneo,ciudad,valor) VALUES(?,?,?)", (conservar, r["ciudad"], r["valor"]))
        # si el torneo que se conserva quedó sin configurar (no paga pasaje), hereda el modo del otro
        if modos[conservar] == MODO_NO and modos[eliminar] != MODO_NO:
            c.execute("UPDATE torneos SET paga_pasaje=1 WHERE nombre=?", (conservar,))
            if modos[eliminar] == MODO_UNICO:
                c.execute("INSERT INTO pasaje_unico(torneo) VALUES(?) ON CONFLICT DO NOTHING", (conservar,))
        for tabla, col in (("precios", "torneo"), ("pasajes_torneo", "torneo"), ("pasaje_unico", "torneo"), ("torneos", "nombre")):
            c.execute(f"DELETE FROM {tabla} WHERE {col}=?", (eliminar,))
        c.execute("UPDATE alias_torneos SET torneo=? WHERE torneo=?", (conservar, eliminar))
        c.execute("INSERT INTO alias_torneos(alias_norm,torneo) VALUES(?,?) "
                  "ON CONFLICT(alias_norm) DO UPDATE SET torneo=excluded.torneo", (norm(eliminar), conservar))
    res["conservado"], res["eliminado"] = conservar, eliminar
    return res


def contar_no_cc() -> int:
    with db() as c:
        return c.execute(f"SELECT COUNT(*) AS n FROM servicios WHERE NOT ({sql_cc()})").fetchone()["n"]


def borrar_no_cc() -> int:
    """Borra de la base los servicios cuyo cobro no es CC (cargados antes de activar el filtro)."""
    with db() as c:
        n = c.execute(f"SELECT COUNT(*) AS n FROM servicios WHERE NOT ({sql_cc()})").fetchone()["n"]
        c.execute(f"DELETE FROM servicios WHERE NOT ({sql_cc()})")
    return n


def listar_arbitros():
    with db() as c:
        return [dict(r) for r in c.execute(
            "SELECT a.id, a.nombre, a.residencia, u.id AS usuario_id "
            "FROM arbitros a LEFT JOIN usuarios u ON u.arbitro_id=a.id ORDER BY a.nombre")]


def agregar_arbitro(nombre, residencia=None):
    try:
        with db() as c:
            c.execute("INSERT INTO arbitros(nombre,nombre_norm,residencia) VALUES(?,?,?)",
                      (limpiar(nombre), norm(nombre), residencia))
    except _errores_integridad():
        raise ValueError("Ese árbitro ya existe.")


def actualizar_residencia(arbitro_id, residencia):
    with db() as c:
        c.execute("UPDATE arbitros SET residencia=? WHERE id=?", (residencia or None, arbitro_id))


# ----------------------------------------------------- importar designaciones
COLUMNAS = {"fecha": "fecha", "torneo": "torneo", "ciudad": "ciudad", "campo": "campo",
            "categoria": "categoria", "hora": "hora", "arbitro": "arbitro", "partido": "partido",
            "servicio": "servicio", "fase": "fase", "cobro": "cobro"}
REQUERIDAS = ["fecha", "torneo", "categoria", "arbitro", "servicio"]


def _leer_tabla(fuente, nombre):
    if nombre.lower().endswith(".csv"):
        try:
            return pd.read_csv(fuente, header=None, dtype=object, encoding="utf-8-sig")
        except UnicodeDecodeError:
            fuente.seek(0)
            return pd.read_csv(fuente, header=None, dtype=object, encoding="latin-1")
    return pd.read_excel(fuente, header=None, dtype=object)


def importar_designaciones(fuente, nombre_archivo="archivo.xlsx", solo_cc=True, repetidas_cuentan=True) -> dict:
    """Lee el Excel/CSV de designaciones y lo guarda. Devuelve un reporte.
    solo_cc: ignora las filas cuyo Cobro no es CC.
    repetidas_cuentan: una fila idéntica que aparece varias veces en el mismo archivo se cuenta como
    servicios separados (ej. un árbitro que cubre los dos puestos de asistente del mismo partido)."""
    raw = _leer_tabla(fuente, nombre_archivo)

    # 1) encontrar la fila de encabezados (el archivo trae un título arriba)
    hdr = next((i for i, r in raw.iterrows()
                if {"fecha", "arbitro"} <= {norm(v) for v in r if pd.notna(v)}), None)
    if hdr is None:
        raise ValueError("No encontré los encabezados 'Fecha' y 'Árbitro' en el archivo.")

    # 2) ubicar columnas por nombre (tolera el typo 'ipo de partid')
    pos = {}
    for j, v in raw.iloc[hdr].items():
        n = norm(v) if pd.notna(v) else ""
        if n in COLUMNAS:
            pos[COLUMNAS[n]] = j
        elif n.startswith(("tipo de", "ipo de")):
            pos["tipo_partido"] = j
    faltan = [k for k in REQUERIDAS if k not in pos]
    if faltan:
        raise ValueError(f"Faltan columnas obligatorias: {', '.join(faltan)}")

    def val(row, k):
        v = row[pos[k]] if k in pos else None
        return None if v is None or (not isinstance(v, (time,)) and pd.isna(v)) else v

    rep = {"filas": 0, "nuevos": 0, "ya_cargados": 0, "repetidos_archivo": 0, "duplicados": 0,
           "omitidas": [], "arbitros_nuevos": [], "posibles_duplicados": [], "roles_raros": {},
           "lista_nuevos": [], "lista_ya_cargados": [], "lista_repetidos": [], "nuevos_no_cc": 0,
           "no_cc": {}, "lista_identicas": []}
    with db() as c:
        filas_arb = list(c.execute("SELECT id,nombre_norm,nombre FROM arbitros"))
        existentes = {r["nombre_norm"]: r["nombre"] for r in filas_arb}
        ids = {r["nombre_norm"]: r["id"] for r in filas_arb}
        for r in c.execute("SELECT alias_norm, arbitro_id FROM alias_arbitros"):
            ids.setdefault(r["alias_norm"], r["arbitro_id"])  # nombre mal escrito que ya se unió a otro
        # Servicios que ya están en la base, comparados por TODOS sus campos
        en_base, previos = {}, {}
        for r in c.execute("SELECT fecha,hora,torneo,ciudad,campo,categoria,arbitro_id,partido,rol,fase,cobro,tipo_partido,archivo "
                           "FROM servicios"):
            k = _clave_servicio(r["fecha"], r["hora"], r["torneo"], r["ciudad"], r["campo"], r["categoria"],
                                r["arbitro_id"], r["partido"], r["rol"], r["fase"], r["cobro"], r["tipo_partido"])
            previos[k] = previos.get(k, 0) + 1
            en_base.setdefault(k, r["archivo"] or "")
        alias_t = {r["alias_norm"]: r["torneo"] for r in c.execute("SELECT alias_norm, torneo FROM alias_torneos")}
        vistos = {}  # clave -> fila de Excel donde apareció primero en este archivo
        veces = {}   # clave -> cuántas filas idénticas van en este archivo
        torneos_ok = set()
        for i in range(hdr + 1, len(raw)):
            row = raw.iloc[i]
            if not any(pd.notna(x) for j, x in row.items() if j != pos["fecha"]):
                continue  # fila separadora (solo trae la fecha)
            rep["filas"] += 1
            excel_row = i + 1
            nombre = val(row, "arbitro")
            if nombre is None:
                rep["omitidas"].append((excel_row, "Sin nombre de árbitro"))
                continue
            nombre = limpiar(nombre)
            fecha = parse_fecha(val(row, "fecha"))
            torneo, cat, serv = val(row, "torneo"), val(row, "categoria"), val(row, "servicio")
            problema = ("Fecha no reconocida" if not fecha else "Sin torneo" if torneo is None
                        else "Sin categoría" if cat is None else "Sin servicio (árbitro/asistente)"
                        if serv is None else None)
            if problema:
                rep["omitidas"].append((excel_row, f"{nombre}: {problema}"))
                continue
            if solo_cc and not es_cc(val(row, "cobro")):
                tipo_cobro = limpiar(val(row, "cobro") or "") or "(vacío)"
                rep["no_cc"][tipo_cobro] = rep["no_cc"].get(tipo_cobro, 0) + 1
                continue

            n = norm(nombre)
            if n not in ids:
                parecidos = difflib.get_close_matches(n, list(existentes), n=1, cutoff=0.88)
                c.execute("INSERT INTO arbitros(nombre,nombre_norm) VALUES(?,?)", (nombre, n))
                existentes[n] = nombre
                ids[n] = c.execute("SELECT id FROM arbitros WHERE nombre_norm=?", (n,)).fetchone()["id"]
                rep["arbitros_nuevos"].append(nombre)
                if parecidos:
                    rep["posibles_duplicados"].append((nombre, existentes[parecidos[0]]))
            aid = ids[n]

            torneo, cat, rol = normalizar_torneo(torneo), limpiar(cat), normalizar_rol(serv)
            torneo = alias_t.get(norm(torneo), torneo)  # variante ya unida a otro torneo
            if rol not in ROLES_COBRABLES:
                rep["roles_raros"][rol] = rep["roles_raros"].get(rol, 0) + 1
            hora = parse_hora(val(row, "hora"))
            ciudad = limpiar(val(row, "ciudad") or "")
            campo = limpiar(val(row, "campo") or "")
            partido = limpiar(val(row, "partido") or "")
            fase = limpiar(val(row, "fase") or "")
            cobro = limpiar(val(row, "cobro") or "")
            tipo = limpiar(val(row, "tipo_partido") or "")
            clave = _clave_servicio(fecha, hora, torneo, ciudad, campo, cat, aid, partido, rol, fase, cobro, tipo)
            detalle = {"Fila Excel": excel_row, "Fecha": fecha_bonita(fecha), "Hora": hora, "Torneo": torneo,
                       "Ciudad": ciudad, "Categoría": cat, "Árbitro": nombre, "Servicio": rol,
                       "Partido": partido, "Fase": fase, "Cobro": cobro}

            veces[clave] = veces.get(clave, 0) + 1
            k = veces[clave]  # k-ésima fila idéntica de este archivo
            if k == 1:
                vistos[clave] = excel_row
            else:
                igual = {"Fila Excel": excel_row, "Igual a la fila": vistos[clave],
                         **{kk: v for kk, v in detalle.items() if kk != "Fila Excel"}}
                if not repetidas_cuentan:  # modo estricto: la copia se descarta
                    rep["repetidos_archivo"] += 1
                    rep["lista_repetidos"].append(igual)
                    continue
                rep["lista_identicas"].append(igual)
            if k <= previos.get(clave, 0):  # esa copia ya estaba cargada en una subida anterior
                rep["ya_cargados"] += 1
                rep["lista_ya_cargados"].append({**detalle, "Cargado antes en": en_base.get(clave, "")})
                continue

            if torneo not in torneos_ok:
                c.execute("INSERT INTO torneos(nombre) VALUES(?) ON CONFLICT DO NOTHING", (torneo,))
                torneos_ok.add(torneo)
            uid = hashlib.sha1(("v2|" + "|".join(map(str, clave)) + (f"|copia{k}" if k > 1 else "")).encode()).hexdigest()
            cur = c.execute(
                "INSERT INTO servicios(uid,fecha,hora,torneo,ciudad,campo,categoria,"
                "arbitro_id,partido,rol,fase,cobro,tipo_partido,archivo) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                (uid, fecha, hora, torneo, ciudad, campo, cat, aid, partido, rol, fase, cobro, tipo, nombre_archivo))
            if cur.rowcount:
                rep["nuevos"] += 1
                rep["nuevos_no_cc"] += 0 if es_cc(cobro) else 1
                rep["lista_nuevos"].append(detalle)
            else:
                rep["ya_cargados"] += 1
                rep["lista_ya_cargados"].append({**detalle, "Cargado antes en": ""})
    rep["duplicados"] = rep["ya_cargados"] + rep["repetidos_archivo"]
    return rep


def _clave_servicio(fecha, hora, torneo, ciudad, campo, cat, arbitro_id, partido, rol, fase, cobro, tipo=""):
    """Identidad de un servicio: TODOS los datos de la fila (sin tildes ni mayúsculas)."""
    return (str(fecha), str(hora or ""), norm(normalizar_torneo(torneo or "")), norm(ciudad or ""),
            norm(campo or ""), norm(cat or ""), int(arbitro_id), norm(partido or ""),
            norm(rol or ""), norm(fase or ""), norm(cobro or ""), norm(tipo or ""))


# ------------------------------------------------------------------ calendario
def servicios_por_dia(anio, mes, arbitro_id=None) -> dict:
    """{'2026-09-26': 12, ...}: servicios por día del mes (de toda la corporación o de un solo árbitro)."""
    ini = date(anio, mes, 1)
    fin = date(anio + (mes == 12), mes % 12 + 1, 1)
    q = "SELECT fecha, COUNT(*) AS n FROM servicios WHERE fecha>=? AND fecha<?"
    p = [ini.isoformat(), fin.isoformat()]
    if arbitro_id:
        q += " AND arbitro_id=?"
        p.append(arbitro_id)
    with db() as c:
        return {r["fecha"]: r["n"] for r in c.execute(q + " GROUP BY fecha", p)}


def servicios_del_dia(fecha_iso, arbitro_id=None) -> pd.DataFrame:
    q = ("SELECT s.hora AS \"Hora\", s.torneo AS \"Torneo\", s.ciudad AS \"Ciudad\", s.campo AS \"Campo\", "
         "s.categoria AS \"Categoría\", a.nombre AS \"Árbitro\", s.rol AS \"Servicio\", s.partido AS \"Partido\" "
         "FROM servicios s JOIN arbitros a ON a.id=s.arbitro_id WHERE s.fecha=?")
    p = [fecha_iso]
    if arbitro_id:
        q += " AND s.arbitro_id=?"
        p.append(arbitro_id)
    with db() as c:
        df = consulta_df(c, q + " ORDER BY s.hora, s.torneo, s.campo, s.partido", p)
    return df.drop(columns=["Árbitro"]) if arbitro_id else df


# --------------------------------------------------- precios, pasajes, listas
def listar_torneos():
    with db() as c:
        return [r["nombre"] for r in c.execute("SELECT nombre FROM torneos ORDER BY nombre")]


def rango_fechas(arbitro_id=None):
    with db() as c:
        if arbitro_id:
            r = c.execute("SELECT MIN(fecha) AS a, MAX(fecha) AS b FROM servicios WHERE arbitro_id=?", (arbitro_id,)).fetchone()
        else:
            r = c.execute("SELECT MIN(fecha) AS a, MAX(fecha) AS b FROM servicios").fetchone()
    return (date.fromisoformat(r["a"]), date.fromisoformat(r["b"])) if r["a"] else None


MODO_NO, MODO_RESIDENCIA, MODO_UNICO = "No paga pasaje", "Según residencia del árbitro", "Valor único (sin importar residencia)"
MODOS_PASAJE = [MODO_NO, MODO_RESIDENCIA, MODO_UNICO]


def _modos_pasaje(c) -> dict:
    out = {}
    for r in c.execute("SELECT t.nombre, t.paga_pasaje, u.torneo AS unico FROM torneos t "
                       "LEFT JOIN pasaje_unico u ON u.torneo=t.nombre"):
        out[r["nombre"]] = (MODO_UNICO if r["unico"] else MODO_RESIDENCIA if r["paga_pasaje"] else MODO_NO)
    return out


def tabla_torneos():
    with db() as c:
        con_cc = {r["torneo"] for r in c.execute(f"SELECT DISTINCT torneo FROM servicios WHERE {sql_cc()}")}
        modos = {t: m for t, m in _modos_pasaje(c).items() if t in con_cc}
    return pd.DataFrame({"Torneo": list(modos), "Pasaje": list(modos.values())}).sort_values("Torneo", ignore_index=True)


def guardar_torneos(df):
    with db() as c:
        for _, r in df.iterrows():
            modo = r["Pasaje"]
            c.execute("UPDATE torneos SET paga_pasaje=? WHERE nombre=?", (0 if modo == MODO_NO else 1, r["Torneo"]))
            if modo == MODO_UNICO:
                c.execute("INSERT INTO pasaje_unico(torneo) VALUES(?) ON CONFLICT DO NOTHING", (r["Torneo"],))
            else:
                c.execute("DELETE FROM pasaje_unico WHERE torneo=?", (r["Torneo"],))


def torneos_pasaje_unico():
    with db() as c:
        return [t for t, m in _modos_pasaje(c).items() if m == MODO_UNICO]


def _lista_ciudades(c, torneo=None, solo_con_partidos=False):
    """Ciudades para poner pasaje: las que ya tienen partidos primero y luego todos los
    municipios de Cundinamarca. Sin repetir aunque estén escritas distinto (tildes, mayúsculas)."""
    if torneo:
        filas = c.execute(f"SELECT DISTINCT ciudad FROM servicios WHERE torneo=? AND ciudad<>'' AND {sql_cc()}", (torneo,))
    else:
        filas = c.execute(f"SELECT DISTINCT ciudad FROM servicios WHERE ciudad<>'' AND {sql_cc()}")
    oficiales = {norm(m): m for m in MUNICIPIOS_CUNDINAMARCA}
    con_partidos = {}
    for r in filas:
        k = norm(r["ciudad"])
        con_partidos.setdefault(k, oficiales.get(k) or limpiar(r["ciudad"]).title())
    nombres = dict(con_partidos)
    if not solo_con_partidos:
        for k, v in oficiales.items():
            nombres.setdefault(k, v)
    orden = sorted(nombres, key=lambda k: (k not in con_partidos, k))
    return [nombres[k] for k in orden]


def tabla_pasajes_torneo(torneo, solo_con_partidos=False):
    with db() as c:
        ciudades = _lista_ciudades(c, torneo, solo_con_partidos)
        actual = {norm(r["ciudad"]): r["valor"] for r in c.execute(
            "SELECT ciudad,valor FROM pasajes_torneo WHERE torneo=?", (torneo,))}
    return pd.DataFrame({"Ciudad del partido": ciudades,
                         "Pasaje": [actual.get(norm(x)) for x in ciudades]}).astype({"Pasaje": float})


def guardar_pasajes_torneo(torneo, df):
    with db() as c:
        previos = [r["ciudad"] for r in c.execute("SELECT ciudad FROM pasajes_torneo WHERE torneo=?", (torneo,))]
        for _, r in df.iterrows():
            ciu = str(r["Ciudad del partido"]).upper()
            for p in previos:  # borra variantes escritas distinto (sin tilde, etc.)
                if p != ciu and norm(p) == norm(ciu):
                    c.execute("DELETE FROM pasajes_torneo WHERE torneo=? AND ciudad=?", (torneo, p))
            if pd.notna(r["Pasaje"]):
                c.execute("INSERT INTO pasajes_torneo(torneo,ciudad,valor) VALUES(?,?,?) "
                          "ON CONFLICT(torneo,ciudad) DO UPDATE SET valor=excluded.valor",
                          (torneo, ciu, float(r["Pasaje"])))
            else:
                c.execute("DELETE FROM pasajes_torneo WHERE torneo=? AND ciudad=?", (torneo, ciu))


def tabla_precios():
    """Combinaciones torneo/categoría/rol de servicios con cobro CC + su precio."""
    marcas = ",".join("?" * len(ROLES_COBRABLES))
    with db() as c:
        df = consulta_df(
            c, "SELECT s.torneo, s.categoria, s.rol, p.valor "
               f"FROM (SELECT DISTINCT torneo,categoria,rol FROM servicios WHERE rol IN ({marcas}) AND {sql_cc()}) s "
               "LEFT JOIN precios p ON p.torneo=s.torneo AND p.categoria=s.categoria AND p.rol=s.rol "
               "ORDER BY s.torneo, s.categoria, s.rol", ROLES_COBRABLES)
    df.columns = ["Torneo", "Categoría", "Rol", "Valor"]
    df["Valor"] = df["Valor"].astype(float)
    return df


def guardar_precios(df):
    with db() as c:
        for _, r in df.iterrows():
            if pd.notna(r["Valor"]):
                c.execute("INSERT INTO precios(torneo,categoria,rol,valor) VALUES(?,?,?,?) "
                          "ON CONFLICT(torneo,categoria,rol) DO UPDATE SET valor=excluded.valor",
                          (r["Torneo"], r["Categoría"], r["Rol"], float(r["Valor"])))
            else:
                c.execute("DELETE FROM precios WHERE torneo=? AND categoria=? AND rol=?",
                          (r["Torneo"], r["Categoría"], r["Rol"]))


def tabla_pasajes(residencia, solo_con_partidos=False):
    with db() as c:
        ciudades = _lista_ciudades(c, None, solo_con_partidos)
        actual = {norm(r["ciudad"]): r["valor"] for r in c.execute(
            "SELECT ciudad,valor FROM pasajes WHERE residencia=?", (residencia,))}
    return pd.DataFrame({"Ciudad del partido": ciudades,
                         "Pasaje": [actual.get(norm(x)) for x in ciudades]}).astype({"Pasaje": float})


def guardar_pasajes(residencia, df):
    with db() as c:
        previos = [r["ciudad"] for r in c.execute("SELECT ciudad FROM pasajes WHERE residencia=?", (residencia,))]
        for _, r in df.iterrows():
            ciu = str(r["Ciudad del partido"]).upper()
            for p in previos:  # borra variantes escritas distinto (sin tilde, etc.)
                if p != ciu and norm(p) == norm(ciu):
                    c.execute("DELETE FROM pasajes WHERE residencia=? AND ciudad=?", (residencia, p))
            if pd.notna(r["Pasaje"]):
                c.execute("INSERT INTO pasajes(residencia,ciudad,valor) VALUES(?,?,?) "
                          "ON CONFLICT(residencia,ciudad) DO UPDATE SET valor=excluded.valor",
                          (residencia, ciu, float(r["Pasaje"])))
            else:
                c.execute("DELETE FROM pasajes WHERE residencia=? AND ciudad=?", (residencia, ciu))


# -------------------------------------------------------------------- cuenta
def calcular_cuenta(arbitro_id, filtros) -> dict:
    """filtros: lista de {'torneo': str, 'desde': date, 'hasta': date}.
    El pasaje se cobra UNA sola vez por día en cada torneo, sin importar cuántos servicios
    o categorías haya tenido el árbitro ese día."""
    with db() as c:
        arb = c.execute("SELECT * FROM arbitros WHERE id=?", (arbitro_id,)).fetchone()
        frames = []
        for f in filtros:
            q = "SELECT * FROM servicios WHERE arbitro_id=? AND fecha BETWEEN ? AND ?"
            p = [arbitro_id, f["desde"].isoformat(), f["hasta"].isoformat()]
            if f.get("torneo") and f["torneo"] != TODOS:
                q += " AND torneo=?"
                p.append(f["torneo"])
            frames.append(consulta_df(c, q, p))
        precios = {(r["torneo"], r["categoria"], r["rol"]): r["valor"] for r in c.execute("SELECT * FROM precios")}
        modos = _modos_pasaje(c)
        pasajes_t = {(r["torneo"], norm(r["ciudad"])): r["valor"] for r in c.execute("SELECT * FROM pasajes_torneo")}
        pasajes = {(r["residencia"], norm(r["ciudad"])): r["valor"] for r in c.execute("SELECT * FROM pasajes")}

    df = pd.concat(frames, ignore_index=True).drop_duplicates("id") if frames else pd.DataFrame()
    res = {"arbitro": arb["nombre"], "residencia": arb["residencia"], "filas": [],
           "total": 0.0, "sin_precio": [], "otros": {}, "sin_pasaje": [], "sin_residencia": False,
           "descuentos": [], "total_descuentos": 0.0, "neto": 0.0, "no_cc": 0}
    if df.empty:
        return res
    solo_cc = df["cobro"].map(es_cc)  # la cuenta de cobro solo incluye servicios con cobro CC
    res["no_cc"] = int((~solo_cc).sum())
    df = df[solo_cc]
    if df.empty:
        return res

    otros = df[~df["rol"].isin(ROLES_COBRABLES)]
    res["otros"] = otros["rol"].value_counts().to_dict()
    df = df[df["rol"].isin(ROLES_COBRABLES)]

    pasaje_cobrado = set()  # (torneo, fecha) que ya tienen su pasaje
    for (torneo, fecha, cat), g in df.sort_values(["fecha", "torneo"]).groupby(["torneo", "fecha", "categoria"], sort=False):
        n_as = int((g["rol"] == ROL_ASISTENTE).sum())
        n_c = int((g["rol"] == ROL_CENTRAL).sum())
        n_em = int((g["rol"] == ROL_EMERGENTE).sum())
        v_as = precios.get((torneo, cat, ROL_ASISTENTE))
        v_c = precios.get((torneo, cat, ROL_CENTRAL))
        v_em = precios.get((torneo, cat, ROL_EMERGENTE))
        aviso = []
        for n, v, rol in ((n_as, v_as, ROL_ASISTENTE), (n_c, v_c, ROL_CENTRAL), (n_em, v_em, ROL_EMERGENTE)):
            if n and v is None:
                aviso.append(f"sin precio de {rol}")
                if (torneo, cat, rol) not in res["sin_precio"]:
                    res["sin_precio"].append((torneo, cat, rol))
        subtotal = n_as * (v_as or 0) + n_c * (v_c or 0) + n_em * (v_em or 0)

        pasaje = 0.0
        if (torneo, fecha) not in pasaje_cobrado:  # solo la primera fila del día en ese torneo lleva pasaje
            pasaje_cobrado.add((torneo, fecha))
            modo = modos.get(torneo, MODO_NO)
            dia = df[(df["torneo"] == torneo) & (df["fecha"] == fecha)]["ciudad"].dropna()
            dia = dia[dia.astype(str).str.strip() != ""]
            ciudad = dia.mode().iloc[0].upper() if len(dia) else ""
            if modo == MODO_UNICO:  # mismo valor sin importar dónde viva el árbitro
                pasaje = pasajes_t.get((torneo, norm(ciudad)))
                if pasaje is None:
                    pasaje = 0.0
                    aviso.append(f"sin pasaje único a {ciudad.title()}")
                    if (f"Único: {torneo}", ciudad) not in res["sin_pasaje"]:
                        res["sin_pasaje"].append((f"Único: {torneo}", ciudad))
            elif modo == MODO_RESIDENCIA:
                if not arb["residencia"]:
                    res["sin_residencia"] = True
                else:
                    pasaje = pasajes.get((arb["residencia"], norm(ciudad)))
                    if pasaje is None:
                        pasaje = 0.0
                        aviso.append(f"sin pasaje {arb['residencia']}→{ciudad.title()}")
                        if (arb["residencia"], ciudad) not in res["sin_pasaje"]:
                            res["sin_pasaje"].append((arb["residencia"], ciudad))
        res["filas"].append({"Torneo": torneo, "Fecha": fecha, "Categ.": cat,
                             "Cant. As.": n_as, "Valor unit. Asistencias": v_as or 0,
                             "Cant. C.": n_c, "Valor unit. Centros": v_c or 0,
                             "Cant. E.": n_em, "Valor unit. Emergentes": v_em or 0,
                             "Subtotal": subtotal, "Pasaje": pasaje,
                             "Valor Total": subtotal + pasaje, "Aviso": "; ".join(aviso)})
        res["total"] += subtotal + pasaje
    res["neto"] = res["total"]
    return res


# ------------------------------------------------------- multas y mensualidades
def agregar_cargo(arbitro_id, tipo, concepto, fecha, valor):
    if tipo not in TIPOS_CARGO:
        raise ValueError("Tipo de cargo no válido.")
    if not valor or float(valor) <= 0:
        raise ValueError("El valor debe ser mayor que cero.")
    with db() as c:
        c.execute("INSERT INTO cargos(arbitro_id,tipo,concepto,fecha,valor,saldado) VALUES(?,?,?,?,?,0)",
                  (arbitro_id, tipo, limpiar(concepto), fecha.isoformat(), float(valor)))


def listar_cargos(arbitro_id):
    with db() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM cargos WHERE arbitro_id=? ORDER BY fecha DESC, id DESC", (arbitro_id,))]


def cargos_pendientes(arbitro_id):
    with db() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM cargos WHERE arbitro_id=? AND saldado=0 ORDER BY fecha, id", (arbitro_id,))]


def guardar_cargos(df):
    """df con columnas id, Concepto, Valor, Saldado, Eliminar."""
    with db() as c:
        for _, r in df.iterrows():
            if bool(r["Eliminar"]):
                c.execute("DELETE FROM cargos WHERE id=?", (int(r["id"]),))
                continue
            c.execute("UPDATE cargos SET concepto=?, saldado=? WHERE id=?",
                      (limpiar(r["Concepto"]), int(bool(r["Saldado"])), int(r["id"])))
            if pd.notna(r["Valor"]) and float(r["Valor"]) > 0:
                c.execute("UPDATE cargos SET valor=? WHERE id=?", (float(r["Valor"]), int(r["id"])))


def marcar_saldados(claves):
    """Marca como pagadas las multas ('c<id>') y mensualidades ('m<id>') que se descontaron en una cuenta."""
    with db() as c:
        for k in claves:
            k = str(k)
            if k.startswith("c"):
                c.execute("UPDATE cargos SET saldado=1 WHERE id=?", (int(k[1:]),))
            elif k.startswith("m"):
                c.execute("UPDATE mensualidades SET saldado=1, abonado=valor WHERE id=?", (int(k[1:]),))


# ----------------------------------------------------------------- mensualidades
def mes_actual() -> str:
    return date.today().strftime("%Y-%m")


def nombre_mes(mes_iso) -> str:
    a, m = str(mes_iso).split("-")
    return f"{MESES[int(m) - 1]} {a}"


def parse_mes(v, anio_defecto=None):
    """Devuelve 'AAAA-MM'. Acepta 'Octubre', 'oct 2026', '2026-10', '10/2026', una fecha o el número del mes."""
    if v is None or (not isinstance(v, str) and not hasattr(v, "year") and pd.isna(v)):
        return None
    if hasattr(v, "year") and hasattr(v, "month"):
        return None if pd.isna(v) else f"{v.year:04d}-{v.month:02d}"
    anio = None
    try:
        if anio_defecto is not None and not pd.isna(anio_defecto):
            anio = int(float(anio_defecto))
    except (TypeError, ValueError):
        anio = None
    s = norm(v)
    m = re.fullmatch(r"(20\d{2})[-/](\d{1,2})", s) or re.fullmatch(r"(\d{1,2})[-/](20\d{2})", s)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        a, b = (a, b) if a > 12 else (b, a)
        return f"{a:04d}-{b:02d}" if 1 <= b <= 12 else None
    y = re.search(r"(20\d{2})", s)
    if y:
        anio = int(y.group(1))
    mes = None
    try:
        num = float(s)
        mes = int(num) if num == int(num) and 1 <= int(num) <= 12 else None
    except ValueError:
        for i, nm in enumerate([norm(x) for x in MESES], 1):
            if re.search(r"\b" + nm[:3], s):
                mes = i
                break
    if not mes:
        return None
    return f"{(anio or date.today().year):04d}-{mes:02d}"


def _es_si(v) -> bool:
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return False
    if isinstance(v, (int, float)):
        return v > 0
    return norm(v) in {"si", "s", "x", "ok", "pago", "pagado", "paga", "cancelado", "1", "true", "yes"}


def _a_pesos(v):
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    d = re.sub(r"\D", "", str(v))
    return float(d) if d else None


def importar_mensualidades(fuente, nombre_archivo="mensualidades.xlsx") -> dict:
    """Excel con: Árbitro | Mes | (Año) | Debe | Pagó (Sí/No). Cada subida actualiza lo que ya existía."""
    raw = _leer_tabla(fuente, nombre_archivo)
    ARB, MES = {"arbitro", "arbitros", "nombre"}, {"mes", "periodo"}
    ANIO = {"ano", "anio"}
    VAL = {"debe", "valor", "mensualidad", "cuota", "saldo", "monto", "valor mensualidad"}
    PAGO = {"pago", "pagado", "estado", "paga"}
    ABONO = {"abono", "abonado", "abonos"}
    hdr = next((i for i, r in raw.iterrows()
                if {norm(v) for v in r if pd.notna(v)} & ARB and {norm(v) for v in r if pd.notna(v)} & MES), None)
    if hdr is None:
        raise ValueError("No encontré los encabezados 'Árbitro' y 'Mes' en el archivo.")
    pos = {}
    for j, v in raw.iloc[hdr].items():
        n = norm(v) if pd.notna(v) else ""
        for clave, conj in (("arbitro", ARB), ("mes", MES), ("anio", ANIO), ("valor", VAL), ("pago", PAGO), ("abono", ABONO)):
            if n in conj and clave not in pos:
                pos[clave] = j
    if "valor" not in pos:
        raise ValueError("Falta la columna con lo que debe cada mes (llámala 'Debe').")

    def val(row, k):
        if k not in pos:
            return None
        v = row[pos[k]]
        return None if v is None or (not isinstance(v, str) and not hasattr(v, "year") and pd.isna(v)) else v

    rep = {"filas": 0, "nuevas": 0, "actualizadas": 0, "sin_cambios": 0, "omitidas": [],
           "no_encontrados": [], "repetidas": []}
    with db() as c:
        ids = {r["nombre_norm"]: r["id"] for r in c.execute("SELECT id,nombre_norm FROM arbitros")}
        for r in c.execute("SELECT alias_norm, arbitro_id FROM alias_arbitros"):
            ids.setdefault(r["alias_norm"], r["arbitro_id"])  # variantes de nombre ya unidas
        vistos = {}
        for i in range(hdr + 1, len(raw)):
            row = raw.iloc[i]
            if not any(pd.notna(x) for x in row.values):
                continue
            rep["filas"] += 1
            fila = i + 1
            nombre = val(row, "arbitro")
            if nombre is None:
                rep["omitidas"].append((fila, "Sin nombre de árbitro"))
                continue
            nombre = limpiar(nombre)
            mes = parse_mes(val(row, "mes"), val(row, "anio"))
            if not mes:
                rep["omitidas"].append((fila, f"{nombre}: mes no reconocido"))
                continue
            valor = _a_pesos(val(row, "valor"))
            if valor is None:
                rep["omitidas"].append((fila, f"{nombre} / {nombre_mes(mes)}: sin valor en 'Debe'"))
                continue
            aid = ids.get(norm(nombre))
            if aid is None:
                cerca = difflib.get_close_matches(norm(nombre), list(ids), n=1, cutoff=0.75)
                rep["no_encontrados"].append((fila, nombre, cerca[0] if cerca else ""))
                continue
            pagado = _es_si(val(row, "pago")) if "pago" in pos else False
            abonado = None  # None = el Excel no trae la columna: se conserva lo que ya había
            if "abono" in pos:
                abonado = max(0.0, _a_pesos(val(row, "abono")) or 0.0)
            if valor == 0:
                pagado = True  # no debe nada ese mes
            if not pagado and abonado is not None and valor > 0 and abonado >= valor:
                pagado = True  # abonó todo
            if pagado:
                abonado = valor
            elif abonado is not None:
                abonado = min(abonado, valor)
            if (aid, mes) in vistos:
                rep["repetidas"].append((fila, nombre, nombre_mes(mes)))
            vistos[(aid, mes)] = (valor, pagado, abonado)  # si se repite, vale la última fila
        for (aid, mes), (valor, pagado, abonado) in vistos.items():
            ex = c.execute("SELECT id,valor,saldado,abonado FROM mensualidades WHERE arbitro_id=? AND mes=?", (aid, mes)).fetchone()
            if ex is None:
                c.execute("INSERT INTO mensualidades(arbitro_id,mes,valor,saldado,abonado) VALUES(?,?,?,?,?)",
                          (aid, mes, valor, int(pagado), abonado or 0.0))
                rep["nuevas"] += 1
                continue
            if abonado is None:  # sin columna Abonó: se conserva el abono, salvo que se desmarcó el pago
                abonado = 0.0 if (ex["saldado"] and not pagado) else float(ex["abonado"])
            if float(ex["valor"]) != valor or bool(ex["saldado"]) != pagado or float(ex["abonado"]) != abonado:
                c.execute("UPDATE mensualidades SET valor=?, saldado=?, abonado=? WHERE id=?",
                          (valor, int(pagado), abonado, ex["id"]))
                rep["actualizadas"] += 1
            else:
                rep["sin_cambios"] += 1
    return rep


def exportar_mensualidades() -> bytes:
    """Excel para editar y volver a subir: lo que hay en la base (o una fila por árbitro si está vacío)."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    with db() as c:
        filas = [(r["nombre"], r["mes"], r["valor"], r["saldado"], r["abonado"]) for r in c.execute(
            "SELECT a.nombre, m.mes, m.valor, m.saldado, m.abonado FROM mensualidades m "
            "JOIN arbitros a ON a.id=m.arbitro_id ORDER BY a.nombre, m.mes")]
        if not filas:
            hoy = mes_actual()
            filas = [(r["nombre"], hoy, None, 0, 0) for r in c.execute("SELECT nombre FROM arbitros ORDER BY nombre")]
    wb = Workbook()
    ws = wb.active
    ws.title = "Mensualidades"
    ws.append(["Árbitro", "Mes", "Año", "Debe", "Abonó", "Pagó"])
    for cell in ws[1]:
        cell.fill = PatternFill("solid", fgColor="0070C0")
        cell.font = Font(name="Arial", bold=True, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center")
    for nombre, mes, valor, saldado, abonado in filas:
        a, m = mes.split("-")
        ws.append([nombre, MESES[int(m) - 1].capitalize(), int(a), valor, abonado or 0, "Sí" if saldado else "No"])
        ws.cell(ws.max_row, 4).number_format = "#,##0"
        ws.cell(ws.max_row, 5).number_format = "#,##0"
    for col, w in zip("ABCDEF", (38, 14, 8, 14, 14, 8)):
        ws.column_dimensions[col].width = w
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def mensualidades_pendientes(arbitro_id, hasta_mes=None):
    """Mensualidades sin pagar desde el inicio hasta el mes actual (no cobra meses futuros).
    El valor es lo que falta: lo cargado menos lo que el árbitro ya abonó."""
    hasta_mes = hasta_mes or mes_actual()
    out = []
    with db() as c:
        for r in c.execute("SELECT * FROM mensualidades WHERE arbitro_id=? AND saldado=0 AND mes<=? "
                           "ORDER BY mes", (arbitro_id, hasta_mes)):
            falta = float(r["valor"]) - float(r["abonado"] or 0)
            if falta <= 0:
                continue
            nota = f" (saldo; ya abonó $ {fmt(r['abonado'])})" if r["abonado"] else ""
            out.append({"clave": f"m{r['id']}", "tipo": "Mensualidad", "mes": r["mes"],
                        "concepto": f"Mensualidad {nombre_mes(r['mes'])}{nota}",
                        "fecha": r["mes"] + "-01", "valor": falta})
    return out


def _estado_mensualidad(fila, mes) -> str:
    """pagada | abono | pendiente | futuro | sin_cargo"""
    if fila is None:
        return "sin_cargo"
    valor, abonado = float(fila["valor"]), float(fila["abonado"] or 0)
    if fila["saldado"] or valor <= 0 or abonado >= valor:
        return "pagada"
    if abonado > 0:
        return "abono"
    return "pendiente" if mes <= mes_actual() else "futuro"


def mensualidades_del_anio(arbitro_id, anio) -> list:
    """Los 12 meses del año con su estado, para dibujar el calendario del árbitro."""
    with db() as c:
        filas = {r["mes"]: r for r in c.execute(
            "SELECT mes,valor,abonado,saldado FROM mensualidades WHERE arbitro_id=? AND mes LIKE ?",
            (arbitro_id, f"{int(anio):04d}-%"))}
    out = []
    for n in range(1, 13):
        mes = f"{int(anio):04d}-{n:02d}"
        f = filas.get(mes)
        out.append({"n": n, "mes": mes, "nombre": MESES[n - 1].capitalize(),
                    "valor": float(f["valor"]) if f else None,
                    "abonado": float(f["abonado"] or 0) if f else 0.0,
                    "saldado": bool(f["saldado"]) if f else False,
                    "estado": _estado_mensualidad(f, mes)})
    return out


def guardar_mensualidades_arbitro(arbitro_id, anio, df):
    """df con columnas n (mes 1-12), Valor, Abonó, Pagada. Valor vacío = ese mes no tiene cargo."""
    with db() as c:
        for _, r in df.iterrows():
            mes = f"{int(anio):04d}-{int(r['n']):02d}"
            ex = c.execute("SELECT id FROM mensualidades WHERE arbitro_id=? AND mes=?", (arbitro_id, mes)).fetchone()
            if pd.isna(r["Valor"]) or float(r["Valor"]) < 0:
                if ex:
                    c.execute("DELETE FROM mensualidades WHERE id=?", (ex["id"],))
                continue
            valor = float(r["Valor"])
            abono = 0.0 if pd.isna(r["Abonó"]) else max(0.0, float(r["Abonó"]))
            pagada = bool(r["Pagada"])
            if valor == 0 or pagada or abono >= valor:
                pagada, abono = True, valor
            if ex:
                c.execute("UPDATE mensualidades SET valor=?, abonado=?, saldado=? WHERE id=?",
                          (valor, abono, int(pagada), ex["id"]))
            else:
                c.execute("INSERT INTO mensualidades(arbitro_id,mes,valor,saldado,abonado) VALUES(?,?,?,?,?)",
                          (arbitro_id, mes, valor, int(pagada), abono))


def generar_mensualidades(desde, hasta, valor, arbitro_id=None) -> int:
    """Crea la mensualidad de cada mes entre 'desde' y 'hasta' ('AAAA-MM') para todos los árbitros
    (o uno solo). Los meses que ya existen no se tocan."""
    if not valor or float(valor) <= 0:
        raise ValueError("El valor debe ser mayor que cero.")
    a, b = int(desde[:4]) * 12 + int(desde[5:]) - 1, int(hasta[:4]) * 12 + int(hasta[5:]) - 1
    if b < a:
        raise ValueError("El mes final es anterior al inicial.")
    if b - a > 35:
        raise ValueError("Máximo 36 meses por vez.")
    meses = [f"{m // 12:04d}-{m % 12 + 1:02d}" for m in range(a, b + 1)]
    n = 0
    with db() as c:
        ids = [arbitro_id] if arbitro_id else [r["id"] for r in c.execute("SELECT id FROM arbitros")]
        ya = {(r["arbitro_id"], r["mes"]) for r in c.execute(
            "SELECT arbitro_id, mes FROM mensualidades WHERE mes>=? AND mes<=?", (meses[0], meses[-1]))}
        for i in ids:
            for mes in meses:
                if (i, mes) not in ya:
                    c.execute("INSERT INTO mensualidades(arbitro_id,mes,valor,saldado,abonado) VALUES(?,?,?,0,0)",
                              (i, mes, float(valor)))
                    n += 1
    return n


def deuda_arbitro(arbitro_id) -> dict:
    """Lo que debe un árbitro hoy: mensualidades (hasta el mes actual) y multas pendientes."""
    mens = mensualidades_pendientes(arbitro_id)
    multas = cargos_pendientes(arbitro_id)
    tm, tx = sum(m["valor"] for m in mens), sum(x["valor"] for x in multas)
    return {"mensualidades": mens, "multas": multas, "total_mensualidades": tm, "total_multas": tx, "total": tm + tx}


def descuentos_pendientes(arbitro_id):
    """Multas + mensualidades pendientes (hasta el mes actual), listas para restar en la cuenta."""
    multas = [{"clave": f"c{x['id']}", "tipo": x["tipo"], "concepto": x["concepto"] or "",
               "fecha": x["fecha"], "valor": x["valor"]} for x in cargos_pendientes(arbitro_id)]
    return sorted(multas + mensualidades_pendientes(arbitro_id), key=lambda d: (d["fecha"], d["clave"]))


def resumen_mensualidades(hasta_mes=None) -> pd.DataFrame:
    hasta_mes = hasta_mes or mes_actual()
    with db() as c:
        df = consulta_df(c, "SELECT a.nombre AS arbitro, m.mes, (m.valor - m.abonado) AS valor FROM mensualidades m "
                            "JOIN arbitros a ON a.id=m.arbitro_id WHERE m.saldado=0 AND m.valor-m.abonado>0 AND m.mes<=? "
                            "ORDER BY a.nombre, m.mes", (hasta_mes,))
    if df.empty:
        return pd.DataFrame(columns=["Árbitro", "Meses pendientes", "Total que debe", "Meses"])
    out = df.groupby("arbitro", sort=True).agg(
        n=("mes", "count"), total=("valor", "sum"),
        meses=("mes", lambda x: ", ".join(nombre_mes(m) for m in x))).reset_index()
    return pd.DataFrame({"Árbitro": out["arbitro"], "Meses pendientes": out["n"],
                         "Total que debe": out["total"], "Meses": out["meses"]})


def aplicar_descuentos(res, cargos):
    """Resta de la cuenta los cargos elegidos (lista de dicts de cargos)."""
    res["descuentos"] = list(cargos)
    res["total_descuentos"] = float(sum(d["valor"] for d in cargos))
    res["neto"] = res["total"] - res["total_descuentos"]
    return res


def exportar_xlsx(res: dict) -> bytes:
    """Excel con el mismo estilo de la tabla de ejemplo (encabezado azul)."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    wb = Workbook()
    ws = wb.active
    ws.title = "Cuenta"
    azul = PatternFill("solid", fgColor="0070C0")
    blanco = Font(name="Arial", bold=True, color="FFFFFF")
    borde = Border(*(Side(style="thin", color="999999"),) * 4)
    centro = Alignment(horizontal="center", vertical="center", wrap_text=True)

    ws["A1"] = f"Cuenta de cobro - {res['arbitro']}"
    ws["A1"].font = Font(name="Arial", bold=True, size=13)
    ws.append([])
    con_em = any(f["Cant. E."] for f in res["filas"])
    enc = ["Torneo", "Fecha", "Categ.", "Cant. As.", "Valor unitario Asistencias",
           "Cant. C.", "Valor unitario Centros"]
    if con_em:
        enc += ["Cant. E.", "Valor unitario Emergentes"]
    enc.append("Valor Total")
    ncol = len(enc)
    letras = "ABCDEFGHIJ"[:ncol]
    ws.append(enc)
    for cell in ws[3]:
        cell.fill, cell.font, cell.alignment, cell.border = azul, blanco, centro, borde
    for f in res["filas"]:
        total = fmt(f["Subtotal"]) + (f"\nPasaje: {fmt(f['Pasaje'])}" if f["Pasaje"] else "")
        fila = [f["Torneo"], fecha_bonita(f["Fecha"]), f["Categ."], f["Cant. As."],
                f["Valor unit. Asistencias"], f["Cant. C."], f["Valor unit. Centros"]]
        if con_em:
            fila += [f["Cant. E."], f["Valor unit. Emergentes"]]
        ws.append(fila + [total])
        for cell in ws[ws.max_row]:
            cell.border, cell.alignment, cell.font = borde, centro, Font(name="Arial")
        for col in ("E", "G") + (("I",) if con_em else ()):
            ws[f"{col}{ws.max_row}"].number_format = "#,##0"
    def fila_total(etiqueta, valor, relleno=True):
        ws.append([etiqueta] + [""] * (ncol - 2) + [valor])
        r = ws.max_row
        ws.merge_cells(f"A{r}:{letras[-2]}{r}")
        for cell in ws[r]:
            cell.border, cell.alignment = borde, centro
            cell.font = blanco if relleno else Font(name="Arial")
            if relleno:
                cell.fill = azul
        ws[f"{letras[-1]}{r}"].number_format = "#,##0"

    fila_total("Total General", res["total"])
    if res.get("descuentos"):
        for d in res["descuentos"]:
            conc = d.get("concepto") or ""
            etiqueta = conc if conc.lower().startswith(d["tipo"].lower()) else f"{d['tipo']}: {conc}"
            fila_total(etiqueta, -d["valor"], relleno=False)
        fila_total("Total a pagar", res["neto"])
    for col, w in zip(letras, (22, 16, 10, 10, 18, 10, 18, 10, 18, 20)[:ncol - 1] + (20,)):
        ws.column_dimensions[col].width = w
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
