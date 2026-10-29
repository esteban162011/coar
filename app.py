"""Cuentas Coarcun · INTERFAZ (app.py). Ejecutar con:  streamlit run app.py

Aquí están las pantallas. Cada pantalla es una sección separada y cada función tiene un comentario
que explica qué hace. La lógica de cálculo está en core.py.

SECCIONES DE ESTE ARCHIVO (búscalas por su número con Ctrl+F «SECCIÓN n»)
   1. INGRESO Y REGISTRO
   2. CUENTA DE COBRO
   3. CARGAR DESIGNACIONES
   4. CALENDARIO DE SERVICIOS
   5. PRECIOS Y PASAJES
   6. MENSUALIDADES
   7. MULTAS
   8. ÁRBITROS Y PERFIL
   9. MENÚ PRINCIPAL
  10. EDITAR Y BORRAR DESIGNACIONES

CÓMO QUITAR O PONER FUNCIONES (comentando una línea)
  Las líneas marcadas con [DESACTIVABLE: ...] se pueden comentar con # para apagar esa función
  y descomentar para volver a encenderla. Cada una es una sola línea independiente:
    · descuentos en la cuenta
    · aviso de deuda al árbitro
    · menú Mensualidades
    · menú Multas
    · menú Mis mensualidades
"""
# -----------------------------------------------------------------------------
# Importaciones
# -----------------------------------------------------------------------------
import calendar
from datetime import date, timedelta
from pathlib import Path
import pandas as pd
import streamlit as st
import core

# ==============================================================================
# CONFIGURACIÓN DE LA PÁGINA, LOGO Y ESTILO
# ------------------------------------------------------------------------------
# Esto se ejecuta una vez al abrir la app: título, logo, tablas de la base y colores.
# ==============================================================================

# Logo de la corporación.
LOGO = Path(__file__).parent / "logo.png"  # escudo de la corporación (debe estar junto a app.py)
# Título, ícono y ancho de la página.
st.set_page_config(page_title="Cuentas Coarcun", page_icon=str(LOGO) if LOGO.exists() else "⚽", layout="wide")
# --- mostrar_logo ---------------------------------------------------------------
# Qué hace: Muestra el escudo de la corporación (si existe logo.png junto a app.py).
def mostrar_logo(ancho):
    if LOGO.exists():
        st.image(str(LOGO), width=ancho)
# Crea las tablas de la base si no existen y el código de administrador la primera vez.
core.init_db()
core.codigo_admin()  # crea codigo_admin.txt la primera vez que se abre la app
# Colores de la interfaz (azul de la corporación).
st.markdown("""
<style>
h1, h2, h3 { color: #0070C0; }
div[data-testid="stMetricValue"] { color: #0070C0; }
.stButton > button[kind="primary"] { background-color: #0070C0; border-color: #0070C0; }
div[data-testid="stImage"] img { border-radius: 12px; }
</style>""", unsafe_allow_html=True)
# Usuario que inició sesión (None = nadie todavía).
st.session_state.setdefault("user", None)


# ==============================================================================
# SECCIÓN 1 · INGRESO Y REGISTRO
# ------------------------------------------------------------------------------
# Pantalla de inicio de sesión y de creación de cuenta (administrador o
# árbitro).
# ==============================================================================

# --- pantalla_ingreso ---------------------------------------------------------
# Qué hace: Pantalla de ingreso: iniciar sesión, crear la primera cuenta de
# administrador o registrarse como árbitro.
def pantalla_ingreso():
    c_logo, c_titulo = st.columns([1, 6], vertical_alignment="center")
    with c_logo:
        mostrar_logo(110)
    with c_titulo:
        st.title("Cuentas Coarcun")
        st.caption("Corporación Arbitral de Cundinamarca")
    t_ing, t_arb, t_adm = st.tabs(["Ingresar", "Primera vez (árbitro)", "Crear administrador"])

    with t_ing, st.form("login"):
        nombre = st.text_input("Nombre completo")
        clave = st.text_input("Contraseña", type="password")
        if st.form_submit_button("Ingresar", type="primary"):
            u = core.autenticar(nombre, clave)
            if u:
                st.session_state.user = u
                st.rerun()
            st.error("Nombre o contraseña incorrectos.")

    with t_arb, st.form("registro_arbitro"):
        st.caption("Escribe tu nombre completo, tal como aparece en las designaciones.")
        nombre = st.text_input("Nombre completo")
        residencia = st.selectbox("Lugar de residencia", core.RESIDENCIAS)
        c1 = st.text_input("Crea tu contraseña (mínimo 6 caracteres)", type="password")
        c2 = st.text_input("Repite la contraseña", type="password")
        forzar = st.checkbox("Mi nombre no aparece en las designaciones todavía, crear mi cuenta de todas formas")
        if st.form_submit_button("Crear mi cuenta", type="primary"):
            if c1 != c2:
                st.error("Las contraseñas no coinciden.")
            else:
                try:
                    core.registrar_arbitro_por_nombre(nombre, c1, residencia, forzar)
                    st.success("Cuenta creada. Ya puedes ingresar en la pestaña «Ingresar».")
                except LookupError:
                    sug = core.sugerir_nombres(nombre)
                    if sug:
                        st.warning("No encontré ese nombre exacto. ¿Eres alguno de estos? "
                                   "Escríbelo exactamente así: " + " · ".join(sug))
                    else:
                        st.warning("Ese nombre no aparece en las designaciones cargadas. Revisa cómo lo escribiste. "
                                   "Si es correcto y aún no te han designado, marca la casilla de arriba para crear la cuenta.")
                except ValueError as e:
                    st.error(str(e))

    with t_adm, st.form("registro_admin"):
        if core.codigo_admin() is None:
            st.error("Falta configurar el código secreto: agrega COARCUN_ADMIN_CODE en los Secrets de la app.")
        elif not core.hay_administradores() and not core.usa_postgres():
            st.info(f"Aún no hay administradores. El código secreto está en el archivo "
                    f"`{core.CODIGO_FILE}` (junto a la app).")
        nombre = st.text_input("Nombre completo del administrador")
        c1 = st.text_input("Contraseña", type="password")
        c2 = st.text_input("Repite la contraseña", type="password")
        codigo = st.text_input("Código secreto de administradores", type="password")
        if st.form_submit_button("Crear administrador", type="primary"):
            if not core.verificar_codigo_admin(codigo):
                st.error("Código secreto incorrecto.")
            elif c1 != c2:
                st.error("Las contraseñas no coinciden.")
            elif not nombre.strip():
                st.error("Escribe tu nombre.")
            else:
                try:
                    core.crear_usuario(nombre, c1, "admin")
                    st.success("Administrador creado. Ya puedes ingresar.")
                except ValueError as e:
                    st.error(str(e))


# ==============================================================================
# SECCIÓN 2 · CUENTA DE COBRO
# ------------------------------------------------------------------------------
# Elegir torneo y fechas, calcular la cuenta, aplicar descuentos (solo el
# administrador) y descargar el Excel.
# ==============================================================================

# --- pagina_cuenta ------------------------------------------------------------
# Qué hace: PÁGINA PRINCIPAL DE LA CUENTA DE COBRO. El árbitro ve solo la
# suya; el administrador elige árbitro y aplica los descuentos.
def pagina_cuenta(user):
    st.header("Cuenta de cobro")
    if st.session_state.get("msg_cuenta"):
        st.success(st.session_state.pop("msg_cuenta"))
    if user["rol"] == "admin":
        arbs = core.listar_arbitros()
        if not arbs:
            st.info("Aún no hay árbitros. Carga primero un archivo de designaciones.")
            return
        opciones = {a["nombre"]: a["id"] for a in arbs}
        nombre = st.selectbox("Árbitro", list(opciones))
        arbitro_id = opciones[nombre]
    else:
        arbitro_id = user["arbitro_id"]

    # 1) filtros: uno o varios torneos, cada uno con su rango de fechas
    torneos = [core.TODOS] + core.listar_torneos()
    rango = core.rango_fechas()
    desde0, hasta0 = rango if rango else (date.today() - timedelta(days=30), date.today())

    n = st.session_state.setdefault("n_filtros", 1)
    filtros = []
    for i in range(n):
        c1, c2, c3 = st.columns([2, 1, 1])
        t = c1.selectbox("Torneo", torneos, key=f"torneo_{i}")
        d = c2.date_input("Desde", desde0, key=f"desde_{i}")
        h = c3.date_input("Hasta", hasta0, key=f"hasta_{i}")
        filtros.append({"torneo": t, "desde": d, "hasta": h})

    # 2) botones para agregar o quitar torneos y para calcular
    b1, b2, b3, _ = st.columns([1.3, 1.3, 1, 3])
    if b1.button("➕ Agregar otro torneo"):
        st.session_state.n_filtros += 1
        st.rerun()
    if n > 1 and b2.button("➖ Quitar el último"):
        st.session_state.n_filtros -= 1
        st.rerun()
    if b3.button("Calcular", type="primary"):
        if any(f["desde"] > f["hasta"] for f in filtros):
            st.error("Una de las fechas «Desde» es posterior a «Hasta».")
        else:
            st.session_state.resultado = (arbitro_id, core.calcular_cuenta(arbitro_id, filtros))

    # 3) mostrar el resultado del último cálculo
    guardado = st.session_state.get("resultado")
    if not guardado or guardado[0] != arbitro_id:
        return
    res = guardado[1]
    st.divider()
    if not res["filas"]:
        if res["no_cc"]:
            st.warning(f"Hay {res['no_cc']} servicios en ese rango, pero ninguno con cobro CC, "
                       "así que no entran a la cuenta de cobro.")
        else:
            st.warning("No hay servicios en ese rango de fechas y torneo.")
        return

    st.subheader(res["arbitro"])
    df = pd.DataFrame(res["filas"])
    vista = pd.DataFrame({
        "Torneo": df["Torneo"], "Fecha": df["Fecha"].map(core.fecha_bonita), "Categ.": df["Categ."],
        "Cant. As.": df["Cant. As."], "Valor unit. Asistencias": df["Valor unit. Asistencias"].map(core.fmt),
        "Cant. C.": df["Cant. C."], "Valor unit. Centros": df["Valor unit. Centros"].map(core.fmt),
        "Pasaje": df["Pasaje"].map(core.fmt), "Valor Total": df["Valor Total"].map(core.fmt)})
    if df["Cant. E."].any():  # columnas de emergente solo si hubo servicios como emergente
        vista.insert(7, "Cant. E.", df["Cant. E."])
        vista.insert(8, "Valor unit. Emergentes", df["Valor unit. Emergentes"].map(core.fmt))
    if user["rol"] == "admin" and df["Aviso"].any():
        vista["Aviso"] = df["Aviso"]
    st.dataframe(vista, hide_index=True)

    # --- descuentos de mensualidades y multas: SOLO el administrador los aplica en la cuenta
    elegidos = []  # descuentos que se aplican a esta cuenta (vacío = ninguno)
    elegidos = bloque_descuentos_admin(arbitro_id, user)  # [DESACTIVABLE: descuentos en la cuenta] comenta esta línea para no descontar nada
    aviso_deuda_arbitro(arbitro_id, user)  # [DESACTIVABLE: aviso de deuda al árbitro] comenta esta línea para ocultar el aviso
    core.aplicar_descuentos(res, elegidos)

    # 4) totales: Total General, Descuentos y Total a pagar
    m1, m2, m3 = st.columns(3)
    m1.metric("Total General", f"$ {core.fmt(res['total'])}")
    if elegidos:
        m2.metric("Descuentos", f"- $ {core.fmt(res['total_descuentos'])}")
        m3.metric("Total a pagar", f"$ {core.fmt(res['neto'])}")
        if res["neto"] < 0:
            st.warning("Los descuentos son mayores que lo que se cobra: el árbitro queda debiendo la diferencia.")

    # 5) avisos de valores que faltan por configurar (precios o pasajes)
    if res["sin_precio"] or res["sin_pasaje"] or res["sin_residencia"]:
        st.warning("Hay valores pendientes por configurar, así que este total puede estar incompleto. "
                   "Avisa a un administrador.")
    if user["rol"] == "admin":
        for torneo, cat, rol in res["sin_precio"]:
            st.caption(f"⚠️ Falta precio: {torneo} / {cat} / {rol}")
        for resid, ciudad in res["sin_pasaje"]:
            st.caption(f"⚠️ Falta pasaje: {resid} → {ciudad.title()}")
        if res["sin_residencia"]:
            st.caption("⚠️ Este árbitro no tiene lugar de residencia y el torneo paga pasaje.")
    if res["no_cc"]:
        st.caption(f"{res['no_cc']} servicios de este rango no se incluyen porque su cobro no es CC (por ejemplo, Efectivo).")
    if res["otros"]:
        st.info("No se cobran (aún no tienen valor definido): "
                + ", ".join(f"{v} como {k}" for k, v in res["otros"].items()))

    # 6) descargar la cuenta en Excel
    st.download_button("⬇️ Descargar en Excel", core.exportar_xlsx(res),
                       f"cuenta_{res['arbitro'].replace(' ', '_')}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    if user["rol"] == "admin" and elegidos:
        st.caption("Cuando ya hayas cobrado esta cuenta, marca los descuentos como pagados para que no se "
                   "resten otra vez en la próxima (las mensualidades pasan a «Pagada» en el calendario del árbitro).")
        if st.button("Marcar descuentos como pagados"):
            core.marcar_saldados([c["clave"] for c in elegidos])
            st.session_state.pop("resultado", None)
            st.session_state["msg_cuenta"] = "Descuentos marcados como pagados. Vuelve a calcular la cuenta."
            st.rerun()


# --- bloque_descuentos_admin --------------------------------------------------
# Qué hace: Tabla de mensualidades y multas pendientes del árbitro; devuelve
# las que el administrador deja marcadas para descontar.
def bloque_descuentos_admin(arbitro_id, user):
    """Tabla con las mensualidades y multas pendientes; devuelve las que el administrador deja marcadas.
    Solo funciona para administradores: a un árbitro le devuelve lista vacía (no se descuenta nada)."""
    if user["rol"] != "admin":
        return []
    pendientes = core.descuentos_pendientes(arbitro_id)
    if not pendientes:
        return []
    st.subheader("Mensualidades y multas pendientes")
    st.caption("Mensualidades hasta el mes actual (si el árbitro abonó, se descuenta solo lo que falta). "
               "Desmarca lo que no quieras descontar en esta cuenta.")
    dfc = pd.DataFrame({
        "clave": [c["clave"] for c in pendientes],
        "Descontar": True,
        "Tipo": [c["tipo"] for c in pendientes],
        "Fecha": [core.fecha_bonita(c["fecha"]) for c in pendientes],
        "Concepto": [c["concepto"] for c in pendientes],
        "Valor": [c["valor"] for c in pendientes]})
    clave = "-".join(c["clave"] for c in pendientes)
    ed = st.data_editor(dfc, hide_index=True, key=f"desc_{arbitro_id}_{clave}",
                        column_order=["Descontar", "Tipo", "Fecha", "Concepto", "Valor"],
                        disabled=["Tipo", "Fecha", "Concepto", "Valor"],
                        column_config={"Valor": st.column_config.NumberColumn(format="$ %d")})
    marcados = set(ed.loc[ed["Descontar"], "clave"])
    return [c for c in pendientes if c["clave"] in marcados]


# --- aviso_deuda_arbitro ------------------------------------------------------
# Qué hace: Mensaje al árbitro con lo que debe. Solo informa: el descuento lo
# aplica el administrador.
def aviso_deuda_arbitro(arbitro_id, user):
    """Al árbitro solo se le informa cuánto debe; el descuento lo aplica el administrador.
    Si quien mira es administrador no muestra nada."""
    if user["rol"] == "admin":
        return
    deuda = core.deuda_arbitro(arbitro_id)
    if deuda["total"] > 0:
        st.info(f"Tienes pendiente $ {core.fmt(deuda['total'])} entre mensualidades y multas. "
                "Míralo en «Mis mensualidades». El administrador lo descuenta al generar tu cuenta de cobro.")


# ==============================================================================
# SECCIÓN 3 · CARGAR DESIGNACIONES
# ------------------------------------------------------------------------------
# Subir el Excel de la comisión, ver cuáles servicios son nuevos o ya estaban,
# y resolver nombres parecidos.
# ==============================================================================

# --- pagina_cargar ------------------------------------------------------------
# Qué hace: Subir el Excel de designaciones y mostrar el reporte: nuevos, ya
# cargados, repetidos e ignorados por no ser CC.
def pagina_cargar():
    st.header("Cargar designaciones")
    st.caption("Sube el Excel (.xlsx) o CSV de la comisión designadora. Un servicio se considera repetido solo si "
               "TODOS sus datos coinciden (fecha, hora, torneo, ciudad, campo, categoría, árbitro, partido, "
               "servicio, fase y cobro). Se pueden subir varios archivos a la vez.")
    # 1) elegir archivos y opciones de carga
    archivos = st.file_uploader("Archivos", type=["xlsx", "csv"], accept_multiple_files=True)
    solo_cc = st.checkbox("Guardar solo los servicios con cobro CC", value=True,
                          help="Las filas con otro cobro (por ejemplo Efectivo) se ignoran por completo.")
    cuentan = st.checkbox("Si una fila idéntica se repite en el mismo archivo, contarla como servicio aparte", value=True,
                          help="Sirve, por ejemplo, cuando un árbitro cubre los dos puestos de asistente del mismo partido. "
                               "Desmárcalo si esas filas repetidas son un error de copiado del Excel.")
    # 2) procesar cada archivo y mostrar su reporte
    if archivos and st.button("Procesar archivos", type="primary"):
        for f in archivos:
            st.subheader(f.name)
            try:
                r = core.importar_designaciones(f, f.name, solo_cc, cuentan)
            except Exception as e:
                st.error(f"No se pudo leer: {e}")
                continue
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Servicios nuevos", r["nuevos"])
            c2.metric("Ya estaban cargados", r["ya_cargados"])
            c3.metric("Repetidos en el archivo", r["repetidos_archivo"])
            c4.metric("Filas omitidas", len(r["omitidas"]))
            for titulo, clave, abierto in (("Servicios nuevos", "lista_nuevos", False),
                                           ("Ya estaban cargados", "lista_ya_cargados", True),
                                           ("Filas idénticas dentro del mismo archivo, contadas como servicios aparte "
                                            "(«Igual a la fila» dice con cuál coinciden)", "lista_identicas", True),
                                           ("Repetidos dentro del mismo archivo, descartados (la columna «Igual a la fila» dice con cuál coincide)",
                                            "lista_repetidos", True)):
                if r[clave]:
                    with st.expander(f"{titulo} ({len(r[clave])})", expanded=abierto):
                        st.dataframe(pd.DataFrame(r[clave]), hide_index=True)
            if r["no_cc"]:
                st.info(f"{sum(r['no_cc'].values())} filas se ignoraron porque su cobro no es CC: "
                        + ", ".join(f"{k}: {v}" for k, v in r["no_cc"].items()) + ".")
            if r["nuevos_no_cc"]:
                st.info(f"{r['nuevos_no_cc']} de los servicios nuevos no tienen cobro CC (por ejemplo, Efectivo): "
                        "se guardan, pero no entran a la cuenta de cobro ni a la lista de precios.")
            if r["arbitros_nuevos"]:
                st.info(f"Árbitros nuevos ({len(r['arbitros_nuevos'])}): " + ", ".join(r["arbitros_nuevos"]))
            if r["omitidas"]:
                st.error("Filas omitidas por datos incompletos (corrígelas en el Excel y vuelve a subirlo):")
                st.dataframe(pd.DataFrame(r["omitidas"], columns=["Fila de Excel", "Motivo"]), hide_index=True)
            if r["roles_raros"]:
                st.warning("Servicios con un rol sin valor definido (no se cobran): "
                           + ", ".join(f"{k}: {v}" for k, v in r["roles_raros"].items()))

    n_no_cc = core.contar_no_cc()
    if n_no_cc:
        st.divider()
        st.warning(f"Hay {n_no_cc} servicios guardados cuyo cobro no es CC (se cargaron antes de activar el filtro).")
        if st.checkbox("Sí, quiero borrarlos de la base", key="conf_borrar_no_cc") and st.button("Borrar servicios que no son CC"):
            st.session_state["flash"] = f"Se borraron {core.borrar_no_cc()} servicios que no eran CC."
            st.rerun()

    bloque_torneos_duplicados()
    bloque_duplicados()


# --- bloque_duplicados --------------------------------------------------------
# Qué hace: Pregunta con botones si dos nombres de árbitro parecidos son la
# misma persona.
def bloque_duplicados():
    """Pregunta si dos nombres parecidos (o uno más completo que otro) son la misma persona."""
    pares = core.posibles_duplicados()
    if not pares:
        return
    st.divider()
    st.subheader("¿Son la misma persona?")
    st.caption("Estos nombres se parecen o uno es una versión más corta del otro. Si son la misma persona, elige "
               "con cuál nombre quieres dejarla: se unen sus servicios, multas y mensualidades, y cuando ese "
               "nombre vuelva a aparecer en un Excel se asigna solo. Si no, el programa no vuelve a preguntar por ese par.")
    for p in pares[:15]:
        a, b = p["a_id"], p["b_id"]
        with st.container(border=True):
            st.markdown(f"**«{p['a_nombre']}»** ({p['a_servicios']} servicios) y "
                        f"**«{p['b_nombre']}»** ({p['b_servicios']} servicios). ¿Es la misma persona?")
            opciones = [(a, b, p["a_nombre"]), (b, a, p["b_nombre"])]
            opciones.sort(key=lambda o: o[0] != p["sugerido"])  # primero el nombre más completo
            c1, c2, c3 = st.columns(3)
            for i, (col, (conservar, eliminar, nombre)) in enumerate(zip((c1, c2), opciones)):
                etiqueta = f"Sí, es la misma: dejar «{nombre}»" + (" (más completo)" if i == 0 else "")
                if col.button(etiqueta, key=f"unir_{conservar}_{eliminar}"):
                    try:
                        r = core.unir_arbitros(conservar, eliminar)
                    except ValueError as e:
                        st.error(str(e))
                    else:
                        extra = f" Se quitaron {r['servicios_repetidos']} servicios que quedaron repetidos." if r["servicios_repetidos"] else ""
                        st.session_state["flash"] = (f"Listo: «{r['eliminado']}» se unió a «{r['conservado']}» "
                                                     f"({r['servicios']} servicios pasados).{extra}")
                        st.rerun()
            if c3.button("No, son personas distintas", key=f"distinto_{a}_{b}"):
                core.marcar_distintos(a, b)
                st.session_state["flash"] = "Anotado: son personas distintas, no se vuelve a preguntar."
                st.rerun()
    if len(pares) > 15:
        st.caption(f"Hay {len(pares) - 15} pares más; aparecen cuando resuelvas estos.")


# --- bloque_torneos_duplicados ------------------------------------------------
# Qué hace: Pregunta con botones si dos nombres de torneo parecidos son el
# mismo torneo.
def bloque_torneos_duplicados():
    """Pregunta si dos nombres de torneo (ej. con y sin año) son el mismo."""
    pares = core.torneos_posibles_duplicados()
    if not pares:
        return
    st.divider()
    st.subheader("¿Es el mismo torneo?")
    st.caption("Estos torneos tienen nombres muy parecidos. Si son el mismo, elige con cuál nombre quieres dejarlo: "
               "se unen sus servicios, precios y pasajes, y cuando el otro nombre vuelva a aparecer en un Excel "
               "se asigna solo. Si no, el programa no vuelve a preguntar por ese par.")
    for i, p in enumerate(pares[:15]):
        a, b = p["a"], p["b"]
        with st.container(border=True):
            st.markdown(f"**«{a}»** ({p['a_servicios']} servicios) y **«{b}»** ({p['b_servicios']} servicios). "
                        "¿Es el mismo torneo?")
            c1, c2, c3 = st.columns(3)
            for col, conservar, eliminar in ((c1, a, b), (c2, b, a)):
                if col.button(f"Sí, es el mismo: dejar «{conservar}»", key=f"ut_{i}_{conservar}"):
                    try:
                        r = core.unir_torneos(conservar, eliminar)
                    except ValueError as e:
                        st.error(str(e))
                    else:
                        extra = f" Se quitaron {r['servicios_repetidos']} servicios que quedaron repetidos." if r["servicios_repetidos"] else ""
                        st.session_state["flash"] = (f"Listo: «{r['eliminado']}» se unió a «{r['conservado']}» "
                                                     f"({r['servicios']} servicios pasados).{extra}")
                        st.rerun()
            if c3.button("No, son torneos distintos", key=f"dt_{i}_{a}"):
                core.marcar_torneos_distintos(a, b)
                st.session_state["flash"] = "Anotado: son torneos distintos, no se vuelve a preguntar."
                st.rerun()
    if len(pares) > 15:
        st.caption(f"Hay {len(pares) - 15} pares más; aparecen cuando resuelvas estos.")


# ==============================================================================
# SECCIÓN 4 · CALENDARIO DE SERVICIOS
# ------------------------------------------------------------------------------
# Calendario del mes con los días en que hubo servicios (de la corporación o
# de un solo árbitro).
# ==============================================================================

# --- pagina_calendario --------------------------------------------------------
# Qué hace: Calendario del mes con los días de servicio resaltados y el
# detalle del día elegido.
def pagina_calendario(arbitro_id=None):
    """Calendario de días con servicios: de toda la corporación (admin) o solo del árbitro indicado."""
    st.header("Mi calendario" if arbitro_id else "Calendario de servicios")
    rango = core.rango_fechas(arbitro_id)
    if not rango:
        st.info("Aún no tienes servicios cargados." if arbitro_id else "Aún no hay servicios. Carga primero un archivo de designaciones.")
        return
    ini, fin = rango
    pre = "mi_cal" if arbitro_id else "cal"
    anios = list(range(ini.year, fin.year + 1))
    st.session_state.setdefault(f"{pre}_anio", fin.year)
    st.session_state.setdefault(f"{pre}_mes", fin.month)
    c1, c2, _ = st.columns([1, 1.5, 3])
    anio = c1.selectbox("Año", anios, key=f"{pre}_anio")
    mes = c2.selectbox("Mes", list(range(1, 13)), key=f"{pre}_mes",
                       format_func=lambda m: core.MESES[m - 1].capitalize())
    dias = core.servicios_por_dia(anio, mes, arbitro_id)

    cabeza = "".join(f"<th>{d}</th>" for d in ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"])
    filas = ""
    for sem in calendar.Calendar(0).monthdayscalendar(anio, mes):
        celdas = ""
        for d in sem:
            if d == 0:
                celdas += '<td class="vacio"></td>'
                continue
            n = dias.get(date(anio, mes, d).isoformat())
            celdas += (f'<td class="con"><b>{d}</b><br><span>{n} servicio{"s" if n != 1 else ""}</span></td>' if n
                       else f"<td><b>{d}</b></td>")
        filas += f"<tr>{celdas}</tr>"
    st.markdown(
        "<style>.cal{width:100%;border-collapse:collapse;table-layout:fixed}"
        ".cal th,.cal td{border:1px solid rgba(128,128,128,.35);padding:6px;height:64px;"
        "vertical-align:top;text-align:center}.cal th{height:auto;color:#0070C0}"
        ".cal td.con{background:#0070C0;color:#fff}.cal td.con span{font-size:.8em}</style>"
        f'<table class="cal"><tr>{cabeza}</tr>{filas}</table>', unsafe_allow_html=True)

    m1, m2 = st.columns(2)
    m1.metric("Días con servicios", len(dias))
    m2.metric("Servicios en el mes", sum(dias.values()))
    if not dias:
        st.caption("Ese mes no tiene servicios cargados.")
        return
    dia = st.selectbox("Ver los servicios de un día", sorted(dias), key=f"dia_{pre}_{anio}_{mes}",
                       format_func=lambda x: f"{core.fecha_bonita(x)} ({dias[x]} servicio{'s' if dias[x] != 1 else ''})")
    st.dataframe(core.servicios_del_dia(dia, arbitro_id), hide_index=True)


# ==============================================================================
# SECCIÓN 5 · PRECIOS Y PASAJES
# ------------------------------------------------------------------------------
# Precios por servicio y pasajes por municipio (solo administrador).
# ==============================================================================

# --- pagina_precios -----------------------------------------------------------
# Qué hace: Cuatro pestañas: precios por servicio, tipo de pasaje por torneo,
# pasaje por residencia y pasaje de valor único.
def pagina_precios():
    st.header("Precios y pasajes")
    bloque_torneos_duplicados()
    t1, t2, t3, t4 = st.tabs(["Valor por servicio", "Tipo de pasaje por torneo",
                              "Pasaje según residencia", "Pasaje de valor único"])

    with t1:
        df = core.tabla_precios()
        if df.empty:
            st.info("Carga primero designaciones.")
        else:
            faltan = int(df["Valor"].isna().sum())
            st.caption(f"{faltan} combinaciones sin precio." if faltan else "Todos los precios están definidos.")
            ed = st.data_editor(df, hide_index=True, key="ed_precios",
                                disabled=["Torneo", "Categoría", "Rol"],
                                column_config={"Valor": st.column_config.NumberColumn(min_value=0, step=1000)})
            if st.button("Guardar precios", type="primary"):
                core.guardar_precios(ed)
                st.success("Precios guardados.")
                st.rerun()

    with t2:
        st.caption("Para cada torneo elige: no paga pasaje, paga según dónde vive el árbitro, "
                   "o paga un valor único por ciudad del partido sin importar dónde viva. "
                   "En todos los casos el pasaje se cobra una sola vez por día en cada torneo, "
                   "sin importar cuántos servicios haya tenido el árbitro ese día.")
        df = core.tabla_torneos()
        ed = st.data_editor(df, hide_index=True, key="ed_torneos", disabled=["Torneo"],
                            column_config={"Pasaje": st.column_config.SelectboxColumn(
                                options=core.MODOS_PASAJE, required=True, width="large")})
        if st.button("Guardar torneos"):
            core.guardar_torneos(ed)
            st.success("Guardado.")

    with t3:
        resid = st.selectbox("Lugar de residencia del árbitro", core.RESIDENCIAS)
        solo = st.toggle("Mostrar solo ciudades con partidos cargados", key="solo_res")
        st.caption("Aparecen todos los municipios de Cundinamarca; primero los que ya tienen partidos. "
                   "Deja vacío el pasaje de los que no uses.")
        df = core.tabla_pasajes(resid, solo)
        ed = st.data_editor(df, hide_index=True, key=f"ed_pasajes_{resid}_{solo}",
                            disabled=["Ciudad del partido"],
                            column_config={"Pasaje": st.column_config.NumberColumn(min_value=0, step=1000)})
        if st.button("Guardar pasajes"):
            core.guardar_pasajes(resid, ed)
            st.success("Guardado.")

    with t4:
        unicos = core.torneos_pasaje_unico()
        if not unicos:
            st.info("Ningún torneo tiene pasaje de valor único. Actívalo en la pestaña «Tipo de pasaje por torneo».")
        else:
            torneo = st.selectbox("Torneo", unicos)
            solo_t = st.toggle("Mostrar solo ciudades con partidos en este torneo", key="solo_unico")
            df = core.tabla_pasajes_torneo(torneo, solo_t)
            ed = st.data_editor(df, hide_index=True, key=f"ed_unico_{torneo}_{solo_t}", disabled=["Ciudad del partido"],
                                column_config={"Pasaje": st.column_config.NumberColumn(min_value=0, step=1000)})
            if st.button("Guardar pasajes del torneo"):
                core.guardar_pasajes_torneo(torneo, ed)
                st.success("Guardado.")


# ==============================================================================
# SECCIÓN 6 · MENSUALIDADES
# ------------------------------------------------------------------------------
# Calendario de meses pagados / abonados / pendientes, control general y carga
# por Excel.
# ==============================================================================

# --- _calendario_meses --------------------------------------------------------
# Qué hace: Dibuja los 12 meses del año con color según estén pagados,
# abonados o pendientes.
def _calendario_meses(meses):
    """Dibuja los 12 meses del año con color según el estado de la mensualidad."""
    estilos = {"pagada": ("#2e7d32", "#fff"), "abono": ("#f9a825", "#1b1b1b"), "pendiente": ("#c62828", "#fff"),
               "futuro": ("transparent", "inherit"), "sin_cargo": ("transparent", "inherit")}
    celdas = []
    for m in meses:
        bg, fg = estilos[m["estado"]]
        if m["estado"] == "pagada":
            txt = f"Pagada<br>$ {core.fmt(m['valor'])}" if m["valor"] else "Pagada"
        elif m["estado"] == "abono":
            txt = f"Abonó $ {core.fmt(m['abonado'])}<br>Debe $ {core.fmt(m['valor'] - m['abonado'])}"
        elif m["estado"] == "pendiente":
            txt = f"Debe<br>$ {core.fmt(m['valor'])}"
        elif m["estado"] == "futuro":
            txt = f"$ {core.fmt(m['valor'])}<br>aún no vence"
        else:
            txt = "—"
        celdas.append(f'<td style="background:{bg};color:{fg}"><b>{m["nombre"]}</b><br><span>{txt}</span></td>')
    filas = "".join("<tr>" + "".join(celdas[i:i + 3]) + "</tr>" for i in range(0, 12, 3))
    st.markdown(
        "<style>.mes{width:100%;border-collapse:collapse;table-layout:fixed}"
        ".mes td{border:1px solid rgba(128,128,128,.35);padding:8px;height:72px;vertical-align:top;text-align:center}"
        ".mes span{font-size:.85em}</style>"
        f'<table class="mes">{filas}</table>', unsafe_allow_html=True)
    st.caption("🟩 Pagada · 🟨 Abonó (debe el resto) · 🟥 Debe · Sin color: aún no vence o sin cargo")


# --- pagina_mensualidades -----------------------------------------------------
# Qué hace: Mensualidades: el árbitro ve su calendario y lo que debe; el
# administrador además registra pagos y abonos, genera meses y sube el Excel.
def pagina_mensualidades(user):
    # el administrador ve tres pestañas; el árbitro solo su calendario
    admin = user["rol"] == "admin"
    st.header("Mensualidades" if admin else "Mis mensualidades")
    if admin:
        t_control, t_arbitro, t_gen = st.tabs(["Control general", "Por árbitro", "Generar y Excel"])
    else:
        t_arbitro = st.container()

    if admin:
        with t_control:
            st.caption(f"Lo que se debe hasta {core.nombre_mes(core.mes_actual())}. Los abonos ya están restados.")
            res = core.resumen_mensualidades()
            if res.empty:
                st.success("No hay mensualidades pendientes.")
            else:
                m1, m2 = st.columns(2)
                m1.metric("Total pendiente de la corporación", f"$ {core.fmt(res['Total que debe'].sum())}")
                m2.metric("Árbitros que deben", len(res))
                vista = res.copy()
                vista["Total que debe"] = vista["Total que debe"].map(core.fmt)
                st.dataframe(vista, hide_index=True)

    # --- calendario y deuda de un árbitro (y, para el administrador, la tabla para registrar pagos)
    with t_arbitro:
        if admin:
            arbs = core.listar_arbitros()
            if not arbs:
                st.info("Aún no hay árbitros. Carga primero un archivo de designaciones.")
                return
            opciones = {a["nombre"]: a["id"] for a in arbs}
            aid = opciones[st.selectbox("Árbitro", list(opciones), key="mens_arbitro")]
        else:
            aid = user["arbitro_id"]
        hoy = date.today()
        anio = st.selectbox("Año", list(range(hoy.year - 3, hoy.year + 2)), index=3, key="mens_anio")
        meses = core.mensualidades_del_anio(aid, anio)
        _calendario_meses(meses)

        deuda = core.deuda_arbitro(aid)
        c1, c2, c3 = st.columns(3)
        c1.metric("Mensualidades que debe", f"$ {core.fmt(deuda['total_mensualidades'])}")
        c2.metric("Multas pendientes", f"$ {core.fmt(deuda['total_multas'])}")
        c3.metric("Total que debe", f"$ {core.fmt(deuda['total'])}")
        if deuda["mensualidades"]:
            st.write("**Meses que debe:** " + ", ".join(core.nombre_mes(m["mes"]) for m in deuda["mensualidades"]))
        if deuda["multas"]:
            st.dataframe(pd.DataFrame({"Fecha": [core.fecha_bonita(x["fecha"]) for x in deuda["multas"]],
                                       "Multa": [x["concepto"] for x in deuda["multas"]],
                                       "Valor": [x["valor"] for x in deuda["multas"]]}),
                         hide_index=True, column_config={"Valor": st.column_config.NumberColumn(format="$ %d")})
        if not admin:
            st.caption("Esto es solo informativo: el administrador descuenta estos valores al generar tu cuenta de cobro.")
            return

        # --- registrar pagos y abonos (solo administrador)
        st.subheader("Registrar pagos y abonos")
        st.caption("Pon el valor de la mensualidad de cada mes, marca **Pagada** si ya la pagó, o escribe en **Abonó** "
                   "lo que ha pagado. Un mes sin valor significa que no tiene cargo.")
        df = pd.DataFrame({"n": [m["n"] for m in meses], "Mes": [m["nombre"] for m in meses],
                           "Valor": [m["valor"] for m in meses],
                           "Abonó": [0.0 if m["estado"] == "pagada" else m["abonado"] for m in meses],
                           "Pagada": [m["estado"] == "pagada" for m in meses]})
        firma = hash(tuple((m["valor"], m["abonado"], m["saldado"]) for m in meses))
        ed = st.data_editor(df, hide_index=True, key=f"ed_mens_{aid}_{anio}_{firma}",
                            column_order=["Mes", "Valor", "Abonó", "Pagada"], disabled=["Mes"],
                            column_config={"Valor": st.column_config.NumberColumn(min_value=0, step=1000, format="$ %d"),
                                           "Abonó": st.column_config.NumberColumn(min_value=0, step=1000, format="$ %d")})
        g1, g2 = st.columns([1, 2])
        if g1.button("Guardar mensualidades", type="primary"):
            core.guardar_mensualidades_arbitro(aid, anio, ed)
            st.session_state["flash"] = "Mensualidades guardadas."
            st.rerun()
        with g2.expander("Poner el mismo valor a los meses vacíos de este año"):
            v = st.number_input("Valor mensual", min_value=0, step=1000, key="mens_valor_anio")
            if st.button("Cargar meses vacíos"):
                try:
                    n = core.generar_mensualidades(f"{anio}-01", f"{anio}-12", v, aid)
                    st.session_state["flash"] = f"Se cargaron {n} meses."
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))

    # --- generar meses para todos y cargar/descargar el Excel (solo administrador)
    with t_gen:
        st.subheader("Generar mensualidades para todos los árbitros")
        st.caption("Crea la mensualidad de cada mes del rango para todos. Los meses que ya existen no se tocan.")
        hoy = date.today()
        c1, c2, c3 = st.columns(3)
        d_mes = c1.selectbox("Desde", list(range(1, 13)), index=0, key="gen_d_mes",
                             format_func=lambda m: core.MESES[m - 1].capitalize())
        d_anio = c1.number_input("Año inicial", 2020, 2100, hoy.year, key="gen_d_anio")
        h_mes = c2.selectbox("Hasta", list(range(1, 13)), index=hoy.month - 1, key="gen_h_mes",
                             format_func=lambda m: core.MESES[m - 1].capitalize())
        h_anio = c2.number_input("Año final", 2020, 2100, hoy.year, key="gen_h_anio")
        valor_gen = c3.number_input("Valor mensual", min_value=0, step=1000, key="gen_valor")
        if st.button("Generar para todos"):
            try:
                n = core.generar_mensualidades(f"{int(d_anio)}-{d_mes:02d}", f"{int(h_anio)}-{h_mes:02d}", valor_gen)
                st.session_state["flash"] = f"Se crearon {n} mensualidades nuevas."
                st.rerun()
            except ValueError as e:
                st.error(str(e))

        st.divider()
        st.subheader("Cargar o actualizar desde Excel")
        st.caption("Columnas: **Árbitro, Mes, Año (opcional), Debe, Abonó (opcional), Pagó (Sí/No)**. "
                   "Descarga el estado actual, edítalo y vuelve a subirlo cuando quieras: actualiza lo que ya existía.")
        st.download_button("⬇️ Descargar plantilla / estado actual", core.exportar_mensualidades(),
                           "mensualidades.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        arch = st.file_uploader("Excel de mensualidades", type=["xlsx", "csv"], key="up_mens")
        if arch and st.button("Procesar mensualidades"):
            try:
                r = core.importar_mensualidades(arch, arch.name)
            except Exception as e:
                st.error(f"No se pudo leer: {e}")
            else:
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Nuevas", r["nuevas"])
                c2.metric("Actualizadas", r["actualizadas"])
                c3.metric("Sin cambios", r["sin_cambios"])
                c4.metric("Con problemas", len(r["omitidas"]) + len(r["no_encontrados"]))
                if r["no_encontrados"]:
                    st.error("Nombres que no coinciden con ningún árbitro (corrígelos en el Excel):")
                    st.dataframe(pd.DataFrame(r["no_encontrados"], columns=["Fila de Excel", "Nombre", "¿Quisiste decir?"]),
                                 hide_index=True)
                if r["omitidas"]:
                    st.error("Filas omitidas:")
                    st.dataframe(pd.DataFrame(r["omitidas"], columns=["Fila de Excel", "Motivo"]), hide_index=True)
                if r["repetidas"]:
                    st.warning("Árbitro y mes repetidos en el archivo (se usó la última fila): "
                               + "; ".join(f"fila {f}: {n} / {m}" for f, n, m in r["repetidas"]))


# ==============================================================================
# SECCIÓN 7 · MULTAS
# ------------------------------------------------------------------------------
# Cargar y administrar las multas de cada árbitro (solo administrador).
# ==============================================================================

# --- pagina_cargos ------------------------------------------------------------
# Qué hace: Agregar, editar, saldar o eliminar las multas de un árbitro.
def pagina_cargos():
    st.header("Multas")
    arbs = core.listar_arbitros()
    if not arbs:
        st.info("Aún no hay árbitros. Carga primero un archivo de designaciones.")
        return
    opciones = {a["nombre"]: a["id"] for a in arbs}
    nombre = st.selectbox("Árbitro", list(opciones))
    aid = opciones[nombre]

    with st.form("nueva_multa", clear_on_submit=True):
        c1, c2, c3 = st.columns([2, 1, 1])
        concepto = c1.text_input("Concepto de la multa (ej. Tarjeta roja, inasistencia)")
        fecha = c2.date_input("Fecha", date.today())
        valor = c3.number_input("Valor", min_value=0, step=1000)
        if st.form_submit_button("Agregar multa", type="primary"):
            try:
                core.agregar_cargo(aid, "Multa", concepto, fecha, valor)
                st.success("Multa agregada.")
            except ValueError as e:
                st.error(str(e))

    cargos = core.listar_cargos(aid)
    if cargos:
        pendiente = sum(c["valor"] for c in cargos if not c["saldado"])
        st.metric("Multas pendientes de este árbitro", f"$ {core.fmt(pendiente)}")
        df = pd.DataFrame({
            "id": [c["id"] for c in cargos], "Tipo": [c["tipo"] for c in cargos],
            "Fecha": [core.fecha_bonita(c["fecha"]) for c in cargos],
            "Concepto": [c["concepto"] for c in cargos], "Valor": [c["valor"] for c in cargos],
            "Saldado": [bool(c["saldado"]) for c in cargos], "Eliminar": False})
        ed = st.data_editor(df, hide_index=True, key=f"ed_cargos_{aid}_{len(cargos)}",
                            column_order=["Tipo", "Fecha", "Concepto", "Valor", "Saldado", "Eliminar"],
                            disabled=["Tipo", "Fecha"],
                            column_config={"Valor": st.column_config.NumberColumn(min_value=0, step=1000, format="$ %d")})
        if st.button("Guardar cambios"):
            core.guardar_cargos(ed)
            st.session_state["flash"] = "Cambios guardados."
            st.rerun()
    else:
        st.caption("Este árbitro no tiene multas registradas.")


# ==============================================================================
# SECCIÓN 8 · ÁRBITROS Y PERFIL
# ------------------------------------------------------------------------------
# Lista de árbitros (administrador) y datos propios del árbitro.
# ==============================================================================

# --- pagina_arbitros ----------------------------------------------------------
# Qué hace: Administrador: lista de árbitros, residencia, cuentas y alta
# manual.
def pagina_arbitros():
    st.header("Árbitros")
    bloque_duplicados()
    arbs = core.listar_arbitros()
    df = pd.DataFrame(arbs)
    if not df.empty:
        df["Cuenta"] = df["usuario_id"].notna().map({True: "Sí", False: "Pendiente"})
        df["residencia"] = df["residencia"].fillna("")
        ed = st.data_editor(
            df[["id", "nombre", "residencia", "Cuenta"]].rename(columns={"nombre": "Nombre", "residencia": "Residencia"}),
            hide_index=True, key="ed_arbs", column_order=["Nombre", "Residencia", "Cuenta"],
            disabled=["id", "Nombre", "Cuenta"],
            column_config={"Residencia": st.column_config.SelectboxColumn(options=[""] + core.RESIDENCIAS)})
        if st.button("Guardar residencias"):
            for _, r in ed.iterrows():
                core.actualizar_residencia(int(r["id"]), r["Residencia"])
            st.success("Guardado.")

    with st.expander("Agregar árbitro manualmente"), st.form("nuevo_arbitro", clear_on_submit=True):
        nombre = st.text_input("Nombre completo")
        if st.form_submit_button("Agregar") and nombre.strip():
            try:
                core.agregar_arbitro(nombre)
                st.success("Agregado.")
            except ValueError as e:
                st.error(str(e))

    con_cuenta = {a["nombre"]: a["usuario_id"] for a in arbs if a["usuario_id"]}
    if con_cuenta:
        with st.expander("Restablecer contraseña de un árbitro"), st.form("reset"):
            quien = st.selectbox("Árbitro", list(con_cuenta))
            nueva = st.text_input("Nueva contraseña temporal", type="password")
            if st.form_submit_button("Restablecer"):
                try:
                    core.cambiar_password(con_cuenta[quien], nueva)
                    st.success("Contraseña actualizada.")
                except ValueError as e:
                    st.error(str(e))


# --- pagina_perfil ------------------------------------------------------------
# Qué hace: Datos del árbitro: residencia y cambio de contraseña.
def pagina_perfil(user):
    st.header("Mi perfil")
    arb = next(a for a in core.listar_arbitros() if a["id"] == user["arbitro_id"])
    st.write(f"**{arb['nombre']}**")
    actual = arb["residencia"] if arb["residencia"] in core.RESIDENCIAS else core.RESIDENCIAS[0]
    nueva = st.selectbox("Lugar de residencia", core.RESIDENCIAS, index=core.RESIDENCIAS.index(actual))
    if st.button("Guardar residencia"):
        core.actualizar_residencia(arb["id"], nueva)
        st.success("Guardado.")
    st.divider()
    with st.form("cambio_clave"):
        c1 = st.text_input("Nueva contraseña", type="password")
        if st.form_submit_button("Cambiar contraseña"):
            try:
                core.cambiar_password(user["id"], c1)
                st.success("Contraseña actualizada.")
            except ValueError as e:
                st.error(str(e))


# ==============================================================================
# SECCIÓN 9 · MENÚ PRINCIPAL
# ------------------------------------------------------------------------------
# Arma el menú lateral según el rol y muestra la página elegida. Aquí se
# quitan o ponen opciones del menú.
# ==============================================================================

# --- main ---------------------------------------------------------------------
# Qué hace: Punto de entrada: muestra el ingreso o, si ya inició sesión, el
# menú con las páginas que le corresponden a su rol.
def main():
    user = st.session_state.user
    if not user:
        return pantalla_ingreso()

    with st.sidebar:
        mostrar_logo(100)
        st.markdown("### Cuentas Coarcun")
        st.write(f"**{user['nombre']}**  \n{'Administrador' if user['rol'] == 'admin' else 'Árbitro'}")
        if user["rol"] == "admin":
            paginas = {
                "Cuenta de cobro": lambda: pagina_cuenta(user),
                "Cargar designaciones": pagina_cargar,
                "Editar y borrar designaciones": pagina_editar_designaciones,
                "Calendario": pagina_calendario,
                "Precios y pasajes": pagina_precios,
                "Mensualidades": lambda: pagina_mensualidades(user),  # [DESACTIVABLE: menú Mensualidades]
                "Multas": pagina_cargos,                              # [DESACTIVABLE: menú Multas]
                "Árbitros": pagina_arbitros,
            }
        else:
            paginas = {
                "Mi cuenta de cobro": lambda: pagina_cuenta(user),
                "Mi calendario": lambda: pagina_calendario(user["arbitro_id"]),
                "Mis mensualidades": lambda: pagina_mensualidades(user),  # [DESACTIVABLE: menú Mis mensualidades]
                "Mi perfil": lambda: pagina_perfil(user),
            }
        eleccion = st.radio("Menú", list(paginas), label_visibility="collapsed")
        if st.button("Cerrar sesión"):
            st.session_state.clear()
            st.rerun()
    if st.session_state.get("flash"):
        st.success(st.session_state.pop("flash"))
    paginas[eleccion]()


# ==============================================================================
# SECCIÓN 10 · EDITAR Y BORRAR DESIGNACIONES
# ------------------------------------------------------------------------------
# Solo administrador: corregir el árbitro y los datos de cada partido, borrar
# servicios sueltos o cargas completas, y cambiar el nombre de un árbitro.
# ==============================================================================

# --- _respaldo_excel ----------------------------------------------------------
# Qué hace: Convierte una tabla de servicios en un Excel descargable (respaldo
# de lo que se va a borrar).
def _respaldo_excel(df) -> bytes:
    import io
    buf = io.BytesIO()
    df.drop(columns=["id"], errors="ignore").to_excel(buf, index=False, sheet_name="Servicios")
    return buf.getvalue()


# --- pagina_editar_designaciones ----------------------------------------------
# Qué hace: Página del administrador con tres pestañas: editar o borrar partidos,
# borrar por lote (una carga, un torneo, todo) y cambiar el nombre de un árbitro.
def pagina_editar_designaciones():
    st.header("Editar y borrar designaciones")
    arbs = core.listar_arbitros()
    rango = core.rango_fechas()
    if not arbs or not rango:
        st.info("Aún no hay designaciones. Carga primero un archivo en «Cargar designaciones».")
        return
    nombres = [a["nombre"] for a in arbs]
    id_de = {a["nombre"]: a["id"] for a in arbs}
    t_edit, t_lote, t_arb = st.tabs(["Editar partidos", "Borrar por lote", "Cambiar nombre de árbitro"])

    # ---- Pestaña 1: editar o borrar partidos uno por uno ----
    with t_edit:
        st.caption("Filtra, corrige lo que necesites directamente en la tabla (árbitro, fecha, partido, torneo...) "
                   "y marca «Eliminar» en los servicios que quieras borrar. Nada se guarda hasta que pulses «Guardar cambios».")
        c1, c2, c3, c4 = st.columns(4)
        f_arb = c1.selectbox("Árbitro", ["Todos"] + nombres, key="ed_f_arb")
        f_tor = c2.selectbox("Torneo", ["Todos"] + core.listar_torneos(), key="ed_f_tor")
        f_des = c3.date_input("Desde", rango[0], key="ed_f_des")
        f_has = c4.date_input("Hasta", rango[1], key="ed_f_has")
        filtros = dict(arbitro_id=None if f_arb == "Todos" else id_de[f_arb],
                       torneo=None if f_tor == "Todos" else f_tor, desde=f_des, hasta=f_has)
        total = core.contar_servicios(**filtros)
        df = core.buscar_servicios(**filtros, limite=500)
        if df.empty:
            st.info("No hay servicios con esos filtros.")
        else:
            if total > len(df):
                st.warning(f"Hay {total} servicios con estos filtros; se muestran los primeros {len(df)}. "
                           "Filtra más para ver los demás.")
            else:
                st.caption(f"{total} servicios.")
            tabla = df.copy()
            tabla["Fecha"] = pd.to_datetime(tabla["Fecha"]).dt.date
            tabla["Eliminar"] = False
            torneos_op = sorted(set(core.listar_torneos()) | set(tabla["Torneo"]))
            roles_op = sorted(set(core.ROLES_COBRABLES) | set(tabla["Servicio"]))
            ver = st.session_state.get("ver_servicios", 0)
            ed = st.data_editor(
                tabla, hide_index=True, num_rows="fixed",
                key=f"ed_serv_{ver}_{f_arb}_{f_tor}_{f_des}_{f_has}",
                column_order=["Fecha", "Hora", "Torneo", "Ciudad", "Campo", "Categoría", "Árbitro",
                              "Servicio", "Partido", "Fase", "Cobro", "Eliminar"],
                disabled=["id", "Archivo"],
                column_config={
                    "Fecha": st.column_config.DateColumn(format="DD/MM/YYYY"),
                    "Árbitro": st.column_config.SelectboxColumn(options=nombres, required=True),
                    "Torneo": st.column_config.SelectboxColumn(options=torneos_op, required=True),
                    "Servicio": st.column_config.SelectboxColumn(options=roles_op, required=True),
                })
            n_borrar = int(ed["Eliminar"].sum())
            confirmado = True
            if n_borrar:
                confirmado = st.checkbox(f"Confirmo que quiero borrar {n_borrar} servicio(s) marcados en «Eliminar»",
                                         key=f"conf_borrar_{ver}")
            if st.button("Guardar cambios", type="primary", disabled=not confirmado, key="guardar_serv"):
                try:
                    r = core.guardar_servicios(ed)
                except ValueError as e:
                    st.error(str(e))
                else:
                    st.session_state["ver_servicios"] = ver + 1
                    st.session_state["flash"] = (f"Listo: {r['actualizados']} servicios actualizados, "
                                                 f"{r['eliminados']} borrados.")
                    st.rerun()

    # ---- Pestaña 2: borrar por lote ----
    with t_lote:
        st.caption("Borra muchos servicios de una vez. Los árbitros, torneos, precios, multas y mensualidades NO se borran, "
                   "solo los servicios (partidos) cargados.")
        modo = st.radio("¿Qué quieres borrar?", ["Una carga completa (por archivo)",
                                                 "Por árbitro, torneo o fechas", "TODAS las designaciones"])
        filtros, todo = {}, False
        if modo.startswith("Una carga"):
            archivos = core.listar_archivos_cargados()
            etiquetas = {f"{a['archivo'] or '(sin nombre)'} · {a['n']} servicios · {a['desde']} a {a['hasta']}": a["archivo"]
                         for a in archivos}
            filtros = {"archivo": etiquetas[st.selectbox("Archivo", list(etiquetas))]}
        elif modo.startswith("Por árbitro"):
            c1, c2 = st.columns(2)
            b_arb = c1.selectbox("Árbitro", ["Todos"] + nombres, key="lote_arb")
            b_tor = c2.selectbox("Torneo", ["Todos"] + core.listar_torneos(), key="lote_tor")
            usar_fechas = st.checkbox("Limitar por fechas", key="lote_usar_fechas")
            if usar_fechas:
                c3, c4 = st.columns(2)
                filtros["desde"] = c3.date_input("Desde", rango[0], key="lote_des")
                filtros["hasta"] = c4.date_input("Hasta", rango[1], key="lote_has")
            if b_arb != "Todos":
                filtros["arbitro_id"] = id_de[b_arb]
            if b_tor != "Todos":
                filtros["torneo"] = b_tor
        else:
            todo = True
        if not filtros and not todo:
            st.info("Elige al menos un filtro (árbitro, torneo o fechas) o usa la opción «TODAS las designaciones».")
        else:
            n = core.contar_servicios(**filtros)
            st.metric("Servicios que se borrarían", n)
            if n:
                st.download_button("Descargar respaldo en Excel de lo que se va a borrar",
                                   _respaldo_excel(core.buscar_servicios(**filtros, limite=None)),
                                   file_name="respaldo_designaciones.xlsx",
                                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                if todo:
                    ok = st.text_input("Para confirmar escribe BORRAR TODO", key="lote_todo").strip() == "BORRAR TODO"
                else:
                    ok = st.checkbox(f"Entiendo que se borrarán {n} servicios y no se puede deshacer", key="lote_ok")
                if st.button("Borrar", type="primary", disabled=not ok, key="lote_borrar"):
                    borrados = core.borrar_servicios_filtrados(**filtros, todo=todo)
                    st.session_state["ver_servicios"] = st.session_state.get("ver_servicios", 0) + 1
                    st.session_state["flash"] = f"Se borraron {borrados} servicios."
                    st.rerun()

    # ---- Pestaña 3: cambiar el nombre de un árbitro ----
    with t_arb:
        st.caption("Sirve para corregir un nombre mal escrito (ej. «Maurico» → «Mauricio»). Todos sus servicios, multas y "
                   "mensualidades siguen con él. Si el nombre correcto ya existe como otro árbitro, no lo renombres: "
                   "únelos en «Árbitros».")
        quien = st.selectbox("Árbitro", nombres, key="ren_arb")
        nuevo = st.text_input("Nombre correcto (completo)", value=quien, key=f"ren_nombre_{quien}")
        guardar_var = st.checkbox("Guardar el nombre anterior como variante (si vuelve a venir así en un Excel, "
                                  "se asigna a este árbitro)", value=True, key="ren_var")
        if any(a["nombre"] == quien and a["usuario_id"] for a in arbs):
            st.caption("Este árbitro ya tiene cuenta: el nombre con el que ingresa a la app no cambia.")
        if st.button("Cambiar nombre", type="primary", key="ren_btn"):
            try:
                r = core.renombrar_arbitro(id_de[quien], nuevo, guardar_var)
            except ValueError as e:
                st.error(str(e))
            else:
                st.session_state["flash"] = f"Listo: «{r['anterior']}» ahora es «{r['nuevo']}»."
                st.rerun()


# ==============================================================================
# ARRANQUE DEL PROGRAMA
# ==============================================================================
main()
