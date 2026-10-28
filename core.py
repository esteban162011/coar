"""Cuentas Coarcun · LÓGICA DEL PROGRAMA (core.py)

Aquí está todo lo que NO es pantalla: base de datos, lectura de Excel, cálculo de la cuenta de cobro,
mensualidades, multas y uniones de nombres. Cada bloque está separado por una sección y cada función
tiene un comentario que explica qué hace. Todo vive en este mismo archivo.

SECCIONES DE ESTE ARCHIVO (búscalas por su número con Ctrl+F «SECCIÓN n»)
   1. CONFIGURACIÓN Y CONSTANTES
   2. UTILIDADES DE TEXTO, FECHAS Y FORMATO
   3. BASE DE DATOS
   4. USUARIOS, CONTRASEÑAS E INGRESO
   5. ÁRBITROS
   6. ÁRBITROS CON NOMBRES PARECIDOS (UNIR VARIANTES)
   7. TORNEOS CON NOMBRES PARECIDOS (UNIR VARIANTES)
   8. CARGAR Y ANALIZAR EL EXCEL DE DESIGNACIONES
   9. CONSULTAS DE SERVICIOS Y CALENDARIO
  10. PRECIOS POR TORNEO, CATEGORÍA Y SERVICIO
  11. PASAJES
  12. CÁLCULO DE LA CUENTA DE COBRO
  13. MULTAS
  14. MENSUALIDADES
  15. DESCUENTOS EN LA CUENTA DE COBRO (MULTAS + MENSUALIDADES)
  16. EXPORTAR LA CUENTA DE COBRO A EXCEL

CÓMO QUITAR O PONER FUNCIONES (comentando una línea)
  Las líneas marcadas con [DESACTIVABLE: ...] se pueden comentar con # para apagar esa función
  y descomentar para volver a encenderla. Cada una es una sola línea independiente:
    · solo cobro CC
    · cobrar multas
    · cobrar mensualidades
"""
# -----------------------------------------------------------------------------
# Importaciones
# -----------------------------------------------------------------------------
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


# ==============================================================================
# SECCIÓN 1 · CONFIGURACIÓN Y CONSTANTES
# ------------------------------------------------------------------------------
# Valores fijos que usa todo el programa: rutas, lugares de residencia, roles,
# meses.
# ==============================================================================

# --- DB_PATH ------------------------------------------------------------------
# Qué hace: Ruta del archivo SQLite local (se usa cuando no hay una base
# Postgres configurada).
DB_PATH = os.environ.get("COARCUN_DB", "cuentas_coarcun.db")


# --- CODIGO_FILE --------------------------------------------------------------
# Qué hace: Archivo donde se guarda el código secreto de administrador (solo
# en uso local).
CODIGO_FILE = os.environ.get("COARCUN_CODE_FILE", "codigo_admin.txt")


# --- RESIDENCIAS --------------------------------------------------------------
# Qué hace: Lugares de residencia posibles de un árbitro; con ellos se calcula
# el pasaje.
RESIDENCIAS = ["Fusagasugá", "Bogotá", "La Mesa", "Facatativá",
               "Girardot", "Soacha", "Chía", "Tocancipá"]


# --- MUNICIPIOS_CUNDINAMARCA --------------------------------------------------
# Qué hace: Los 116 municipios de Cundinamarca (más Bogotá): son las ciudades
# a las que se les pone precio de pasaje.
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
    "Villeta", "Viotá", "Yacopí", "Zipacón", "Zipaquirá", "Bogotá", "Chinauta", "Siberia","Briceño", 
]


# --- ROL_CENTRAL --------------------------------------------------------------
# Qué hace: Nombres oficiales de los tres servicios que se cobran: árbitro
# central, asistente y emergente.
ROL_CENTRAL, ROL_ASISTENTE, ROL_EMERGENTE = "Arbitro", "Asistente", "Emergente"


# --- ROLES_COBRABLES ----------------------------------------------------------
# Qué hace: Servicios que tienen precio y entran a la cuenta de cobro.
ROLES_COBRABLES = (ROL_CENTRAL, ROL_ASISTENTE, ROL_EMERGENTE)


# --- TODOS --------------------------------------------------------------------
# Qué hace: Texto del filtro 'todos los torneos' en la cuenta de cobro.
TODOS = "Todos los torneos"


# --- TIPOS_CARGO --------------------------------------------------------------
# Qué hace: Tipos de cargo que se pueden poner a mano (las mensualidades
# vienen de su propia sección).
TIPOS_CARGO = ("Multa",)  # las mensualidades se cargan desde Excel


# --- MESES --------------------------------------------------------------------
# Qué hace: Nombres de los meses en español (se usan para mostrar fechas y
# leer el Excel de mensualidades).
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


# ==============================================================================
# SECCIÓN 2 · UTILIDADES DE TEXTO, FECHAS Y FORMATO
# ------------------------------------------------------------------------------
# Funciones pequeñas que limpian y convierten datos. No tocan la base de
# datos.
# ==============================================================================

# --- norm ---------------------------------------------------------------------
# Qué hace: Pasa un texto a minúsculas, sin tildes ni espacios repetidos.
# Sirve para comparar nombres sin que importen mayúsculas o tildes.
def norm(s) -> str:
    """Minúsculas, sin tildes y sin espacios repetidos (para comparar nombres)."""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().lower()


# --- limpiar ------------------------------------------------------------------
# Qué hace: Quita los espacios sobrantes de un texto.
def limpiar(s) -> str:
    return re.sub(r"\s+", " ", str(s)).strip()


# --- fmt ----------------------------------------------------------------------
# Qué hace: Da formato de pesos a un número, con punto de miles (ej. 20000 →
# 20.000).
def fmt(n) -> str:
    return f"{n:,.0f}".replace(",", ".")


# --- fecha_bonita -------------------------------------------------------------
# Qué hace: Convierte una fecha ISO (2026-09-26) en texto legible (26 de
# Septiembre).
def fecha_bonita(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day:02d} de {MESES[d.month - 1].capitalize()}"


# --- parse_fecha --------------------------------------------------------------
# Qué hace: Entiende las fechas que trae el Excel de designaciones y las
# devuelve en formato ISO.
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


# --- parse_hora ---------------------------------------------------------------
# Qué hace: Convierte la hora del Excel en texto HH:MM.
def parse_hora(v) -> str:
    """Redondea al minuto (el Excel trae basura como 10:59:59.971)."""
    if isinstance(v, time):
        seg = v.hour * 3600 + v.minute * 60 + v.second + v.microsecond / 1e6
        mins = round(seg / 60)
        return f"{(mins // 60) % 24:02d}:{mins % 60:02d}"
    return "" if v is None or pd.isna(v) else str(v)


# --- normalizar_rol -----------------------------------------------------------
# Qué hace: Unifica cómo se escribe el servicio: 'arbitro' → Arbitro,
# 'asistente' → Asistente.
def normalizar_rol(v) -> str:
    n = norm(v)
    return {"arbitro": ROL_CENTRAL, "asistente": ROL_ASISTENTE}.get(n, limpiar(v).capitalize())


# --- normalizar_torneo --------------------------------------------------------
# Qué hace: Unifica cómo se escribe el nombre de un torneo (espacios y puntos
# sobrantes al final).
def normalizar_torneo(v) -> str:
    return limpiar(v).rstrip(". ")


# --- es_cc --------------------------------------------------------------------
# Qué hace: Dice si el cobro de un servicio es CC (acepta 'CC', 'C.C.' o ' cc
# ').
def es_cc(v) -> bool:
    """True si el cobro del servicio es 'CC' (también acepta 'C.C.' o ' cc ')."""
    return re.sub(r"[^a-z]", "", norm(v or "")) == "cc"


# --- sql_cc -------------------------------------------------------------------
# Qué hace: La condición 'cobro = CC' escrita en SQL, para usarla dentro de
# consultas.
def sql_cc(col="cobro") -> str:
    """Misma condición en SQL (SQLite y Postgres)."""
    return f"UPPER(REPLACE(REPLACE(TRIM(COALESCE({col}, '')), '.', ''), ' ', '')) = 'CC'"


# ==============================================================================
# SECCIÓN 3 · BASE DE DATOS
# ------------------------------------------------------------------------------
# Conexión (SQLite local o Postgres en la nube), creación de tablas y
# migraciones.
# ==============================================================================

# --- _cfg ---------------------------------------------------------------------
# Qué hace: Guarda la configuración de la conexión una vez leída.
_cfg = {}


# --- _secreto -----------------------------------------------------------------
# Qué hace: Lee un valor secreto (por ejemplo la dirección de la base) de
# Streamlit o de las variables de entorno.
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


# --- usa_postgres -------------------------------------------------------------
# Qué hace: Dice si la app está usando Postgres (nube) o SQLite (local).
def usa_postgres() -> bool:
    """True si hay DATABASE_URL (nube). Si no, se usa el archivo SQLite local."""
    return bool(_secreto("DATABASE_URL"))


# --- _errores_integridad ------------------------------------------------------
# Qué hace: Errores que pueden saltar al romper una regla de la base (ej.
# nombre repetido).
def _errores_integridad():
    errs = (sqlite3.IntegrityError,)
    if usa_postgres():
        import psycopg2
        errs += (psycopg2.IntegrityError,)
    return errs


# --- _Conn --------------------------------------------------------------------
# Qué hace: Envoltura que hace que SQLite y Postgres se usen igual (mismos '?'
# y filas tipo diccionario).
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


# --- _conectar ----------------------------------------------------------------
# Qué hace: Abre la conexión a la base de datos.
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


# --- db -----------------------------------------------------------------------
# Qué hace: Abre la base para un bloque 'with db() as c:'; guarda los cambios
# al terminar y cierra la conexión.
@contextmanager
def db():
    c = _conectar()
    try:
        yield c
        c.raw.commit()
    finally:
        c.raw.close()


# --- consulta_df --------------------------------------------------------------
# Qué hace: Ejecuta una consulta y devuelve el resultado como tabla de pandas.
def consulta_df(c, sql, params=()):
    """Ejecuta una consulta y devuelve un DataFrame (funciona igual en SQLite y Postgres)."""
    cur = c.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return pd.DataFrame([tuple(r[k] for k in cols) for r in cur.fetchall()], columns=cols)


# --- _SCHEMA ------------------------------------------------------------------
# Qué hace: Definición de todas las tablas de la base (se crean solo si no
# existen).
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


# --- _init_hecho --------------------------------------------------------------
# Qué hace: Recuerda en qué bases ya se crearon las tablas, para no repetirlo
# en cada recarga.
_init_hecho = set()


# --- init_db ------------------------------------------------------------------
# Qué hace: Crea las tablas y aplica las migraciones (por ejemplo, agrega la
# columna de abonos si falta).
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


# ==============================================================================
# SECCIÓN 4 · USUARIOS, CONTRASEÑAS E INGRESO
# ------------------------------------------------------------------------------
# Crear cuentas, verificar contraseñas y enlazar al árbitro con su nombre de
# las designaciones.
# ==============================================================================

# --- _hash --------------------------------------------------------------------
# Qué hace: Convierte una contraseña en un código irreversible (hash) para
# guardarla de forma segura.
def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()


# --- codigo_admin -------------------------------------------------------------
# Qué hace: Devuelve el código secreto necesario para crear administradores.
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


# --- verificar_codigo_admin ---------------------------------------------------
# Qué hace: Comprueba si el código escrito es el código de administrador.
def verificar_codigo_admin(codigo) -> bool:
    real = codigo_admin()
    return bool(real) and hmac.compare_digest(str(codigo).encode(), real.encode())


# --- crear_usuario ------------------------------------------------------------
# Qué hace: Crea una cuenta (administrador o árbitro) con su contraseña.
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


# --- cambiar_password ---------------------------------------------------------
# Qué hace: Cambia la contraseña de un usuario.
def cambiar_password(usuario_id, password):
    if len(password) < 6:
        raise ValueError("La contraseña debe tener al menos 6 caracteres.")
    salt = secrets.token_hex(16)
    with db() as c:
        c.execute("UPDATE usuarios SET pass_hash=?, salt=? WHERE id=?",
                  (_hash(password, salt), salt, usuario_id))


# --- autenticar ---------------------------------------------------------------
# Qué hace: Verifica nombre y contraseña; devuelve los datos del usuario o
# None si no coinciden.
def autenticar(nombre, password):
    with db() as c:
        u = c.execute("SELECT * FROM usuarios WHERE nombre_norm=?", (norm(nombre),)).fetchone()
    if u and hmac.compare_digest(u["pass_hash"], _hash(password, u["salt"])):
        return {"id": u["id"], "nombre": u["nombre"], "rol": u["rol"], "arbitro_id": u["arbitro_id"]}
    return None


# --- hay_administradores ------------------------------------------------------
# Qué hace: Dice si ya existe al menos un administrador (para el primer
# arranque).
def hay_administradores() -> bool:
    with db() as c:
        return c.execute("SELECT 1 FROM usuarios WHERE rol='admin'").fetchone() is not None


# --- arbitros_sin_cuenta ------------------------------------------------------
# Qué hace: Lista los árbitros de las designaciones que todavía no crearon su
# cuenta.
def arbitros_sin_cuenta():
    with db() as c:
        return [dict(r) for r in c.execute(
            "SELECT a.* FROM arbitros a LEFT JOIN usuarios u ON u.arbitro_id=a.id "
            "WHERE u.id IS NULL ORDER BY a.nombre")]


# --- registrar_arbitro --------------------------------------------------------
# Qué hace: Crea la cuenta de un árbitro ya existente y guarda su residencia.
def registrar_arbitro(arbitro_id, password, residencia):
    with db() as c:
        a = c.execute("SELECT nombre FROM arbitros WHERE id=?", (arbitro_id,)).fetchone()
    crear_usuario(a["nombre"], password, "arbitro", arbitro_id)  # falla si ya tiene cuenta
    actualizar_residencia(arbitro_id, residencia)


# --- sugerir_nombres ----------------------------------------------------------
# Qué hace: Propone nombres de árbitros sin cuenta que se parecen al escrito
# (incluye nombres incompletos).
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


# --- registrar_arbitro_por_nombre ---------------------------------------------
# Qué hace: El árbitro escribe su nombre; si coincide con el de las
# designaciones (o con una variante unida) se enlaza su cuenta.
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


# ==============================================================================
# SECCIÓN 5 · ÁRBITROS
# ------------------------------------------------------------------------------
# Lista de árbitros, alta manual y lugar de residencia.
# ==============================================================================

# --- listar_arbitros ----------------------------------------------------------
# Qué hace: Devuelve todos los árbitros ordenados por nombre.
def listar_arbitros():
    with db() as c:
        return [dict(r) for r in c.execute(
            "SELECT a.id, a.nombre, a.residencia, u.id AS usuario_id "
            "FROM arbitros a LEFT JOIN usuarios u ON u.arbitro_id=a.id ORDER BY a.nombre")]


# --- agregar_arbitro ----------------------------------------------------------
# Qué hace: Agrega un árbitro a mano.
def agregar_arbitro(nombre, residencia=None):
    try:
        with db() as c:
            c.execute("INSERT INTO arbitros(nombre,nombre_norm,residencia) VALUES(?,?,?)",
                      (limpiar(nombre), norm(nombre), residencia))
    except _errores_integridad():
        raise ValueError("Ese árbitro ya existe.")


# --- actualizar_residencia ----------------------------------------------------
# Qué hace: Cambia el lugar de residencia de un árbitro.
def actualizar_residencia(arbitro_id, residencia):
    with db() as c:
        c.execute("UPDATE arbitros SET residencia=? WHERE id=?", (residencia or None, arbitro_id))


# ==============================================================================
# SECCIÓN 6 · ÁRBITROS CON NOMBRES PARECIDOS (UNIR VARIANTES)
# ------------------------------------------------------------------------------
# Detecta y une nombres como 'Felipe Figueredo' y 'Andrés Felipe Figueredo
# Castiblanco'.
# ==============================================================================

# --- _claves_de_servicios -----------------------------------------------------
# Qué hace: Agrupa los servicios por su identidad completa; sirve para
# comparar antes y después de unir dos nombres.
def _claves_de_servicios(c, donde, params, torneo=None, ignorar_arbitro=False):
    """{clave: [ids]} de los servicios que cumplen 'donde' (para comparar antes y después de unir)."""
    out = {}
    for r in c.execute("SELECT id,fecha,hora,torneo,ciudad,campo,categoria,arbitro_id,partido,rol,fase,cobro,tipo_partido "
                       "FROM servicios WHERE " + donde + " ORDER BY id", params):
        k = _clave_servicio(r["fecha"], r["hora"], torneo or r["torneo"], r["ciudad"], r["campo"], r["categoria"],
                            0 if ignorar_arbitro else r["arbitro_id"], r["partido"], r["rol"], r["fase"], r["cobro"], r["tipo_partido"])
        out.setdefault(k, []).append(r["id"])
    return out


# --- _quitar_repetidos_al_unir ------------------------------------------------
# Qué hace: Al unir dos nombres, elimina servicios que quedaron duplicados
# pero respeta las filas idénticas legítimas.
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


# --- _tokens_contenidos -------------------------------------------------------
# Qué hace: Dice si un nombre es una versión más corta de otro (ej. 'felipe
# figueredo' dentro de 'andres felipe figueredo').
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


# --- _nombres_parecidos -------------------------------------------------------
# Qué hace: Dice si dos nombres se parecen lo suficiente para preguntar si son
# la misma persona.
def _nombres_parecidos(x, y, umbral) -> bool:
    return _tokens_contenidos(x, y) or difflib.SequenceMatcher(None, x, y).ratio() >= umbral


# --- posibles_duplicados ------------------------------------------------------
# Qué hace: Busca pares de árbitros que podrían ser la misma persona y que aún
# no se han resuelto.
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


# --- marcar_distintos ---------------------------------------------------------
# Qué hace: Anota que dos árbitros son personas diferentes, para no volver a
# preguntar por ese par.
def marcar_distintos(id1, id2):
    """Registra que son personas diferentes para no volver a preguntar."""
    with db() as c:
        n1 = c.execute("SELECT nombre_norm FROM arbitros WHERE id=?", (id1,)).fetchone()
        n2 = c.execute("SELECT nombre_norm FROM arbitros WHERE id=?", (id2,)).fetchone()
        if n1 and n2:
            a, b = sorted((n1["nombre_norm"], n2["nombre_norm"]))
            c.execute("INSERT INTO arbitros_distintos(a_norm,b_norm) VALUES(?,?) ON CONFLICT DO NOTHING", (a, b))


# --- unir_arbitros ------------------------------------------------------------
# Qué hace: Pasa todo (servicios, multas, mensualidades, cuenta) de un árbitro
# a otro y recuerda el nombre eliminado como variante.
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


# ==============================================================================
# SECCIÓN 7 · TORNEOS CON NOMBRES PARECIDOS (UNIR VARIANTES)
# ------------------------------------------------------------------------------
# Detecta y une nombres como 'Copa Santa Fe' y 'Copa Santa Fe 2026'.
# ==============================================================================

# --- _sin_anio ----------------------------------------------------------------
# Qué hace: Quita el año de un nombre de torneo ('copa santa fe 2026' → 'copa
# santa fe').
def _sin_anio(x) -> str:
    return " ".join(re.sub(r"\b(19|20)\d{2}\b", "", x).split())


# --- _torneos_parecidos -------------------------------------------------------
# Qué hace: Dice si dos nombres de torneo parecen ser el mismo (igual salvo el
# año, uno dentro del otro, o casi iguales).
def _torneos_parecidos(x, y, umbral=0.88) -> bool:
    """Mismo nombre salvo el año, uno contenido en el otro, o casi igual (letra mal escrita)."""
    if x == y:
        return False
    sx, sy = _sin_anio(x), _sin_anio(y)
    if sx and sx == sy:
        return True
    return _tokens_contenidos(x, y) or difflib.SequenceMatcher(None, x, y).ratio() >= umbral


# --- torneos_posibles_duplicados ----------------------------------------------
# Qué hace: Busca pares de torneos que podrían ser el mismo y que aún no se
# han resuelto.
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


# --- marcar_torneos_distintos -------------------------------------------------
# Qué hace: Anota que dos torneos son diferentes, para no volver a preguntar
# por ese par.
def marcar_torneos_distintos(a, b):
    x, y = sorted((norm(a), norm(b)))
    with db() as c:
        c.execute("INSERT INTO torneos_distintos(a_norm,b_norm) VALUES(?,?) ON CONFLICT DO NOTHING", (x, y))


# --- unir_torneos -------------------------------------------------------------
# Qué hace: Pasa servicios, precios y pasajes de un torneo a otro y recuerda
# el nombre eliminado como variante.
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


# ==============================================================================
# SECCIÓN 8 · CARGAR Y ANALIZAR EL EXCEL DE DESIGNACIONES
# ------------------------------------------------------------------------------
# Lee el archivo de la comisión designadora, ignora lo que no es CC, detecta
# filas repetidas y guarda los servicios.
# ==============================================================================

# --- COLUMNAS -----------------------------------------------------------------
# Qué hace: Encabezados que se aceptan en el Excel de designaciones y a qué
# dato corresponde cada uno.
COLUMNAS = {"fecha": "fecha", "torneo": "torneo", "ciudad": "ciudad", "campo": "campo",
            "categoria": "categoria", "hora": "hora", "arbitro": "arbitro", "partido": "partido",
            "servicio": "servicio", "fase": "fase", "cobro": "cobro"}


# --- REQUERIDAS ---------------------------------------------------------------
# Qué hace: Columnas sin las cuales no se puede procesar el archivo.
REQUERIDAS = ["fecha", "torneo", "categoria", "arbitro", "servicio"]


# --- _leer_tabla --------------------------------------------------------------
# Qué hace: Lee un archivo .xlsx o .csv y lo devuelve como tabla sin
# interpretar encabezados.
def _leer_tabla(fuente, nombre):
    if nombre.lower().endswith(".csv"):
        try:
            return pd.read_csv(fuente, header=None, dtype=object, encoding="utf-8-sig")
        except UnicodeDecodeError:
            fuente.seek(0)
            return pd.read_csv(fuente, header=None, dtype=object, encoding="latin-1")
    return pd.read_excel(fuente, header=None, dtype=object)


# --- _clave_servicio ----------------------------------------------------------
# Qué hace: Identidad de un servicio: TODOS sus datos juntos (fecha, hora,
# torneo, ciudad, campo, categoría, árbitro, partido, servicio, fase, cobro,
# tipo). Dos servicios son el mismo solo si todo coincide.
def _clave_servicio(fecha, hora, torneo, ciudad, campo, cat, arbitro_id, partido, rol, fase, cobro, tipo=""):
    """Identidad de un servicio: TODOS los datos de la fila (sin tildes ni mayúsculas)."""
    return (str(fecha), str(hora or ""), norm(normalizar_torneo(torneo or "")), norm(ciudad or ""),
            norm(campo or ""), norm(cat or ""), int(arbitro_id), norm(partido or ""),
            norm(rol or ""), norm(fase or ""), norm(cobro or ""), norm(tipo or ""))


# --- importar_designaciones ---------------------------------------------------
# Qué hace: BLOQUE PRINCIPAL DE CARGA: lee el Excel, ignora las filas que no
# son CC, crea árbitros y torneos nuevos, separa nuevos / ya cargados /
# repetidos y guarda los servicios.
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

    # 3) reporte que se devuelve al final (cuántas filas son nuevas, ya cargadas, repetidas, omitidas...)
    rep = {"filas": 0, "nuevos": 0, "ya_cargados": 0, "repetidos_archivo": 0, "duplicados": 0,
           "omitidas": [], "arbitros_nuevos": [], "posibles_duplicados": [], "roles_raros": {},
           "lista_nuevos": [], "lista_ya_cargados": [], "lista_repetidos": [], "nuevos_no_cc": 0,
           "no_cc": {}, "lista_identicas": []}
    with db() as c:
        # 4) cargar de la base lo que ya existe (árbitros, variantes de nombre, servicios) para compararlo con el archivo
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
        # 5) recorrer el archivo fila por fila
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
            # filtro 'solo cobro CC': las demás filas se ignoran por completo
            if solo_cc and not es_cc(val(row, "cobro")):
                tipo_cobro = limpiar(val(row, "cobro") or "") or "(vacío)"
                rep["no_cc"][tipo_cobro] = rep["no_cc"].get(tipo_cobro, 0) + 1
                continue

            # árbitro: se busca por nombre (o por una variante ya unida); si no existe se crea
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

            # filas idénticas dentro del mismo archivo: se cuentan como servicios aparte (o se descartan en modo estricto)
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
            # si esa copia ya estaba guardada de una subida anterior, no se vuelve a guardar
            if k <= previos.get(clave, 0):  # esa copia ya estaba cargada en una subida anterior
                rep["ya_cargados"] += 1
                rep["lista_ya_cargados"].append({**detalle, "Cargado antes en": en_base.get(clave, "")})
                continue

            if torneo not in torneos_ok:
                c.execute("INSERT INTO torneos(nombre) VALUES(?) ON CONFLICT DO NOTHING", (torneo,))
                torneos_ok.add(torneo)
            # servicio nuevo: se guarda
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


# --- contar_no_cc -------------------------------------------------------------
# Qué hace: Cuenta los servicios guardados cuyo cobro no es CC.
def contar_no_cc() -> int:
    with db() as c:
        return c.execute(f"SELECT COUNT(*) AS n FROM servicios WHERE NOT ({sql_cc()})").fetchone()["n"]


# --- borrar_no_cc -------------------------------------------------------------
# Qué hace: Borra de la base los servicios cuyo cobro no es CC (los que se
# cargaron antes de activar el filtro).
def borrar_no_cc() -> int:
    """Borra de la base los servicios cuyo cobro no es CC (cargados antes de activar el filtro)."""
    with db() as c:
        n = c.execute(f"SELECT COUNT(*) AS n FROM servicios WHERE NOT ({sql_cc()})").fetchone()["n"]
        c.execute(f"DELETE FROM servicios WHERE NOT ({sql_cc()})")
    return n


# ==============================================================================
# SECCIÓN 9 · CONSULTAS DE SERVICIOS Y CALENDARIO
# ------------------------------------------------------------------------------
# Servicios por día para el calendario y datos generales (torneos, rango de
# fechas).
# ==============================================================================

# --- servicios_por_dia --------------------------------------------------------
# Qué hace: Cuenta los servicios de cada día de un mes (de toda la corporación
# o de un solo árbitro). Alimenta el calendario.
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


# --- servicios_del_dia --------------------------------------------------------
# Qué hace: Lista los servicios de un día (hora, torneo, campo, árbitro,
# partido).
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


# --- listar_torneos -----------------------------------------------------------
# Qué hace: Devuelve los nombres de todos los torneos.
def listar_torneos():
    with db() as c:
        return [r["nombre"] for r in c.execute("SELECT nombre FROM torneos ORDER BY nombre")]


# --- rango_fechas -------------------------------------------------------------
# Qué hace: Primera y última fecha con servicios (de todos o de un árbitro).
def rango_fechas(arbitro_id=None):
    with db() as c:
        if arbitro_id:
            r = c.execute("SELECT MIN(fecha) AS a, MAX(fecha) AS b FROM servicios WHERE arbitro_id=?", (arbitro_id,)).fetchone()
        else:
            r = c.execute("SELECT MIN(fecha) AS a, MAX(fecha) AS b FROM servicios").fetchone()
    return (date.fromisoformat(r["a"]), date.fromisoformat(r["b"])) if r["a"] else None


# ==============================================================================
# SECCIÓN 10 · PRECIOS POR TORNEO, CATEGORÍA Y SERVICIO
# ------------------------------------------------------------------------------
# Cuánto se paga cada tipo de servicio.
# ==============================================================================

# --- tabla_precios ------------------------------------------------------------
# Qué hace: Combinaciones torneo / categoría / servicio con cobro CC, junto
# con su precio actual.
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


# --- guardar_precios ----------------------------------------------------------
# Qué hace: Guarda los precios editados en la tabla.
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


# ==============================================================================
# SECCIÓN 11 · PASAJES
# ------------------------------------------------------------------------------
# Tipo de pasaje de cada torneo, y valor del pasaje por residencia o por
# ciudad del partido.
# ==============================================================================

# --- MODO_NO ------------------------------------------------------------------
# Qué hace: Tipos de pasaje de un torneo: no paga, según la residencia del
# árbitro, o un valor único por ciudad.
MODO_NO, MODO_RESIDENCIA, MODO_UNICO = "No paga pasaje", "Según residencia del árbitro", "Valor único (sin importar residencia)"


# --- MODOS_PASAJE -------------------------------------------------------------
# Qué hace: Nombres con los que se muestra cada tipo de pasaje en pantalla.
MODOS_PASAJE = [MODO_NO, MODO_RESIDENCIA, MODO_UNICO]


# --- _modos_pasaje ------------------------------------------------------------
# Qué hace: Devuelve el tipo de pasaje de cada torneo.
def _modos_pasaje(c) -> dict:
    out = {}
    for r in c.execute("SELECT t.nombre, t.paga_pasaje, u.torneo AS unico FROM torneos t "
                       "LEFT JOIN pasaje_unico u ON u.torneo=t.nombre"):
        out[r["nombre"]] = (MODO_UNICO if r["unico"] else MODO_RESIDENCIA if r["paga_pasaje"] else MODO_NO)
    return out


# --- tabla_torneos ------------------------------------------------------------
# Qué hace: Tabla para elegir el tipo de pasaje de cada torneo (solo torneos
# con servicios CC).
def tabla_torneos():
    with db() as c:
        con_cc = {r["torneo"] for r in c.execute(f"SELECT DISTINCT torneo FROM servicios WHERE {sql_cc()}")}
        modos = {t: m for t, m in _modos_pasaje(c).items() if t in con_cc}
    return pd.DataFrame({"Torneo": list(modos), "Pasaje": list(modos.values())}).sort_values("Torneo", ignore_index=True)


# --- guardar_torneos ----------------------------------------------------------
# Qué hace: Guarda el tipo de pasaje elegido para cada torneo.
def guardar_torneos(df):
    with db() as c:
        for _, r in df.iterrows():
            modo = r["Pasaje"]
            c.execute("UPDATE torneos SET paga_pasaje=? WHERE nombre=?", (0 if modo == MODO_NO else 1, r["Torneo"]))
            if modo == MODO_UNICO:
                c.execute("INSERT INTO pasaje_unico(torneo) VALUES(?) ON CONFLICT DO NOTHING", (r["Torneo"],))
            else:
                c.execute("DELETE FROM pasaje_unico WHERE torneo=?", (r["Torneo"],))


# --- torneos_pasaje_unico -----------------------------------------------------
# Qué hace: Lista los torneos que pagan un pasaje de valor único.
def torneos_pasaje_unico():
    with db() as c:
        return [t for t, m in _modos_pasaje(c).items() if m == MODO_UNICO]


# --- _lista_ciudades ----------------------------------------------------------
# Qué hace: Ciudades para poner pasaje: primero las que ya tienen partidos CC
# y luego los municipios de Cundinamarca, sin repetir.
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


# --- tabla_pasajes_torneo -----------------------------------------------------
# Qué hace: Tabla de pasaje único por ciudad para un torneo.
def tabla_pasajes_torneo(torneo, solo_con_partidos=False):
    with db() as c:
        ciudades = _lista_ciudades(c, torneo, solo_con_partidos)
        actual = {norm(r["ciudad"]): r["valor"] for r in c.execute(
            "SELECT ciudad,valor FROM pasajes_torneo WHERE torneo=?", (torneo,))}
    return pd.DataFrame({"Ciudad del partido": ciudades,
                         "Pasaje": [actual.get(norm(x)) for x in ciudades]}).astype({"Pasaje": float})


# --- guardar_pasajes_torneo ---------------------------------------------------
# Qué hace: Guarda el pasaje único por ciudad de un torneo.
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


# --- tabla_pasajes ------------------------------------------------------------
# Qué hace: Tabla de pasaje por ciudad para un lugar de residencia.
def tabla_pasajes(residencia, solo_con_partidos=False):
    with db() as c:
        ciudades = _lista_ciudades(c, None, solo_con_partidos)
        actual = {norm(r["ciudad"]): r["valor"] for r in c.execute(
            "SELECT ciudad,valor FROM pasajes WHERE residencia=?", (residencia,))}
    return pd.DataFrame({"Ciudad del partido": ciudades,
                         "Pasaje": [actual.get(norm(x)) for x in ciudades]}).astype({"Pasaje": float})


# --- guardar_pasajes ----------------------------------------------------------
# Qué hace: Guarda el pasaje por ciudad de un lugar de residencia.
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


# ==============================================================================
# SECCIÓN 12 · CÁLCULO DE LA CUENTA DE COBRO
# ------------------------------------------------------------------------------
# Suma servicios y pasajes de un árbitro en las fechas y torneos elegidos (un
# pasaje por día y torneo).
# ==============================================================================

# --- _separar_cc --------------------------------------------------------------
# Qué hace: Deja solo los servicios con cobro CC y cuenta cuántos se dejaron
# por no serlo.
def _separar_cc(df):
    """Devuelve (servicios con cobro CC, cuántos se dejaron por no ser CC)."""
    es_cobro_cc = df["cobro"].map(es_cc)
    return df[es_cobro_cc], int((~es_cobro_cc).sum())


# --- calcular_cuenta ----------------------------------------------------------
# Qué hace: BLOQUE PRINCIPAL DE LA CUENTA: agrupa por torneo, día y categoría,
# multiplica por los precios y suma UN solo pasaje por día y torneo.
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

    # 2) juntar los servicios de todos los filtros (torneo + fechas) sin repetirlos
    df = pd.concat(frames, ignore_index=True).drop_duplicates("id") if frames else pd.DataFrame()
    res = {"arbitro": arb["nombre"], "residencia": arb["residencia"], "filas": [],
           "total": 0.0, "sin_precio": [], "otros": {}, "sin_pasaje": [], "sin_residencia": False,
           "descuentos": [], "total_descuentos": 0.0, "neto": 0.0, "no_cc": 0}
    if df.empty:
        return res
    # Filtro "solo cobro CC": la cuenta incluye únicamente los servicios cuyo Cobro es CC.
    df, res["no_cc"] = _separar_cc(df)  # [DESACTIVABLE: solo cobro CC] comenta esta línea para cobrar TODOS los cobros
    if df.empty:
        return res

    # servicios sin precio definido (ej. otros roles) no se cobran, pero se avisan
    otros = df[~df["rol"].isin(ROLES_COBRABLES)]
    res["otros"] = otros["rol"].value_counts().to_dict()
    df = df[df["rol"].isin(ROLES_COBRABLES)]

    pasaje_cobrado = set()  # (torneo, fecha) que ya tienen su pasaje
    # 3) una fila de la cuenta por cada torneo + día + categoría
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

        # 4) pasaje: se cobra UNA sola vez por día en cada torneo (en la primera fila de ese día)
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


# ==============================================================================
# SECCIÓN 13 · MULTAS
# ------------------------------------------------------------------------------
# Multas que se cargan a cada árbitro y se descuentan en la cuenta de cobro.
# ==============================================================================

# --- agregar_cargo ------------------------------------------------------------
# Qué hace: Agrega una multa a un árbitro.
def agregar_cargo(arbitro_id, tipo, concepto, fecha, valor):
    if tipo not in TIPOS_CARGO:
        raise ValueError("Tipo de cargo no válido.")
    if not valor or float(valor) <= 0:
        raise ValueError("El valor debe ser mayor que cero.")
    with db() as c:
        c.execute("INSERT INTO cargos(arbitro_id,tipo,concepto,fecha,valor,saldado) VALUES(?,?,?,?,?,0)",
                  (arbitro_id, tipo, limpiar(concepto), fecha.isoformat(), float(valor)))


# --- listar_cargos ------------------------------------------------------------
# Qué hace: Lista todas las multas de un árbitro.
def listar_cargos(arbitro_id):
    with db() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM cargos WHERE arbitro_id=? ORDER BY fecha DESC, id DESC", (arbitro_id,))]


# --- cargos_pendientes --------------------------------------------------------
# Qué hace: Lista las multas de un árbitro que todavía no se han pagado.
def cargos_pendientes(arbitro_id):
    with db() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM cargos WHERE arbitro_id=? AND saldado=0 ORDER BY fecha, id", (arbitro_id,))]


# --- guardar_cargos -----------------------------------------------------------
# Qué hace: Guarda los cambios hechos en la tabla de multas (concepto, valor,
# saldada, eliminar).
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


# ==============================================================================
# SECCIÓN 14 · MENSUALIDADES
# ------------------------------------------------------------------------------
# Meses que debe cada árbitro: calendario, abonos, pagos, Excel y deuda total.
# ==============================================================================

# --- mes_actual ---------------------------------------------------------------
# Qué hace: Mes de hoy en formato AAAA-MM.
def mes_actual() -> str:
    return date.today().strftime("%Y-%m")


# --- nombre_mes ---------------------------------------------------------------
# Qué hace: Convierte '2026-10' en 'octubre 2026'.
def nombre_mes(mes_iso) -> str:
    a, m = str(mes_iso).split("-")
    return f"{MESES[int(m) - 1]} {a}"


# --- parse_mes ----------------------------------------------------------------
# Qué hace: Entiende un mes escrito de varias formas ('Octubre', 'oct 2026',
# '2026-10', '10/2026', una fecha o el número).
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


# --- _es_si -------------------------------------------------------------------
# Qué hace: Interpreta una celda de 'Pagó' (Sí, x, ok, pagado...) como
# verdadero.
def _es_si(v) -> bool:
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return False
    if isinstance(v, (int, float)):
        return v > 0
    return norm(v) in {"si", "s", "x", "ok", "pago", "pagado", "paga", "cancelado", "1", "true", "yes"}


# --- _a_pesos -----------------------------------------------------------------
# Qué hace: Convierte una celda de dinero ('$ 15.000', 15000) en número.
def _a_pesos(v):
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    d = re.sub(r"\D", "", str(v))
    return float(d) if d else None


# --- importar_mensualidades ---------------------------------------------------
# Qué hace: BLOQUE DE CARGA DE MENSUALIDADES: lee el Excel (Árbitro, Mes, Año,
# Debe, Abonó, Pagó) y crea o actualiza cada mes de cada árbitro.
def importar_mensualidades(fuente, nombre_archivo="mensualidades.xlsx") -> dict:
    """Excel con: Árbitro | Mes | (Año) | Debe | Pagó (Sí/No). Cada subida actualiza lo que ya existía."""
    raw = _leer_tabla(fuente, nombre_archivo)
    ARB, MES = {"arbitro", "arbitros", "nombre"}, {"mes", "periodo"}
    ANIO = {"ano", "anio"}
    VAL = {"debe", "valor", "mensualidad", "cuota", "saldo", "monto", "valor mensualidad"}
    PAGO = {"pago", "pagado", "estado", "paga"}
    ABONO = {"abono", "abonado", "abonos"}
    # 1) encontrar la fila de encabezados y ubicar cada columna
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
        # 2) leer cada fila: árbitro, mes, valor, abono y si pagó
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
        # 3) guardar: crear los meses nuevos y actualizar los que ya existían
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


# --- exportar_mensualidades ---------------------------------------------------
# Qué hace: Genera el Excel de mensualidades para editarlo y volver a subirlo
# (o una plantilla si está vacío).
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


# --- _estado_mensualidad ------------------------------------------------------
# Qué hace: Decide el estado de un mes: pagada, abono, pendiente, futuro o sin
# cargo.
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


# --- mensualidades_del_anio ---------------------------------------------------
# Qué hace: Los 12 meses de un año de un árbitro con su estado; alimenta el
# calendario de mensualidades.
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


# --- guardar_mensualidades_arbitro --------------------------------------------
# Qué hace: Guarda lo editado en la tabla de meses (valor, abonó, pagada) de
# un árbitro.
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


# --- generar_mensualidades ----------------------------------------------------
# Qué hace: Crea la mensualidad de un rango de meses para todos los árbitros
# (o uno); no toca los meses que ya existen.
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


# --- mensualidades_pendientes -------------------------------------------------
# Qué hace: Mensualidades sin pagar hasta el mes actual; si hubo abono, solo
# cuenta lo que falta.
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


# --- deuda_arbitro ------------------------------------------------------------
# Qué hace: Cuánto debe un árbitro hoy en total (mensualidades hasta el mes
# actual + multas).
def deuda_arbitro(arbitro_id) -> dict:
    """Lo que debe un árbitro hoy: mensualidades (hasta el mes actual) y multas pendientes."""
    mens = mensualidades_pendientes(arbitro_id)
    multas = cargos_pendientes(arbitro_id)
    tm, tx = sum(m["valor"] for m in mens), sum(x["valor"] for x in multas)
    return {"mensualidades": mens, "multas": multas, "total_mensualidades": tm, "total_multas": tx, "total": tm + tx}


# --- resumen_mensualidades ----------------------------------------------------
# Qué hace: Tabla de control: cada árbitro que debe, cuántos meses y cuánto en
# total.
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


# ==============================================================================
# SECCIÓN 15 · DESCUENTOS EN LA CUENTA DE COBRO (MULTAS + MENSUALIDADES)
# ------------------------------------------------------------------------------
# Junta lo que se le descuenta al árbitro en su cuenta y lo marca como pagado.
# ==============================================================================

# --- _multas_como_descuentos --------------------------------------------------
# Qué hace: Convierte las multas pendientes de un árbitro en el formato de
# 'descuento'.
def _multas_como_descuentos(arbitro_id):
    """Las multas pendientes del árbitro, con el formato de un descuento."""
    return [{"clave": f"c{x['id']}", "tipo": x["tipo"], "concepto": x["concepto"] or "",
             "fecha": x["fecha"], "valor": x["valor"]} for x in cargos_pendientes(arbitro_id)]


# --- descuentos_pendientes ----------------------------------------------------
# Qué hace: Junta lo que se puede descontar en la cuenta. AQUÍ SE ACTIVA O
# DESACTIVA el cobro de multas y de mensualidades (comenta la línea que no
# quieras).
def descuentos_pendientes(arbitro_id):
    """Lo que se le puede descontar al árbitro en su cuenta de cobro: multas + mensualidades pendientes."""
    descuentos = []
    descuentos += _multas_como_descuentos(arbitro_id)     # [DESACTIVABLE: cobrar multas] comenta esta línea para NO descontar multas
    descuentos += mensualidades_pendientes(arbitro_id)    # [DESACTIVABLE: cobrar mensualidades] comenta esta línea para NO descontar mensualidades
    return sorted(descuentos, key=lambda d: (d["fecha"], d["clave"]))


# --- aplicar_descuentos -------------------------------------------------------
# Qué hace: Resta los descuentos elegidos del total de la cuenta y calcula el
# total a pagar.
def aplicar_descuentos(res, cargos):
    """Resta de la cuenta los cargos elegidos (lista de dicts de cargos)."""
    res["descuentos"] = list(cargos)
    res["total_descuentos"] = float(sum(d["valor"] for d in cargos))
    res["neto"] = res["total"] - res["total_descuentos"]
    return res


# --- marcar_saldados ----------------------------------------------------------
# Qué hace: Marca como pagadas las multas y mensualidades que se descontaron
# en una cuenta.
def marcar_saldados(claves):
    """Marca como pagadas las multas ('c<id>') y mensualidades ('m<id>') que se descontaron en una cuenta."""
    with db() as c:
        for k in claves:
            k = str(k)
            if k.startswith("c"):
                c.execute("UPDATE cargos SET saldado=1 WHERE id=?", (int(k[1:]),))
            elif k.startswith("m"):
                c.execute("UPDATE mensualidades SET saldado=1, abonado=valor WHERE id=?", (int(k[1:]),))


# ==============================================================================
# SECCIÓN 16 · EXPORTAR LA CUENTA DE COBRO A EXCEL
# ------------------------------------------------------------------------------
# Genera el archivo .xlsx de la cuenta, con los descuentos y el total a pagar.
# ==============================================================================

# --- exportar_xlsx ------------------------------------------------------------
# Qué hace: Genera el Excel de la cuenta de cobro (servicios, pasajes,
# descuentos y total a pagar).
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
