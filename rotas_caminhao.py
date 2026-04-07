import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, time
from zoneinfo import ZoneInfo
import numpy as np
import plotly.express as px
import math

# =========================
# CONFIG
# =========================

CODIGO_ADMIN = "123456"
TOLERANCIA_MINUTOS = 4
TZ = ZoneInfo("America/Sao_Paulo")

st.set_page_config(layout="wide")
st.title("🚛 Controle de Rotas")

# =========================
# SESSION STATE
# =========================

if "logado" not in st.session_state:
    st.session_state.logado = False

if "ultimo_registro" not in st.session_state:
    st.session_state.ultimo_registro = None

if "lat" not in st.session_state:
    st.session_state.lat = None
if "lon" not in st.session_state:
    st.session_state.lon = None

# =========================
# BANCO
# =========================

conn = sqlite3.connect("logistica.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS usuarios(
id INTEGER PRIMARY KEY AUTOINCREMENT,
usuario TEXT,
senha TEXT,
tipo TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS locais(
id INTEGER PRIMARY KEY AUTOINCREMENT,
nome_local TEXT,
qr_code TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS horarios_rota(
id INTEGER PRIMARY KEY AUTOINCREMENT,
turno TEXT,
rota TEXT,
hora_chegada TEXT,
hora_saida TEXT,
local_id INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS registros_rota(
id INTEGER PRIMARY KEY AUTOINCREMENT,
motorista TEXT,
local_id INTEGER,
data_hora TEXT,
status TEXT
)
""")

conn.commit()

# =========================
# FUNÇÕES
# =========================

def filtro_data():
    agora = datetime.now(TZ)
    hoje = agora.date()
    data_escolhida = st.date_input("📅 Filtrar por data", value=hoje)
    data_inicio = datetime.combine(data_escolhida, time.min).replace(tzinfo=TZ)
    data_fim = datetime.combine(data_escolhida, time.max).replace(tzinfo=TZ)
    return data_inicio, data_fim, data_escolhida

def turno_atual():
    agora = datetime.now(TZ).time()
    if time(6,0) <= agora < time(15,10):
        return "A","1º Turno"
    elif time(15,10) <= agora < time(23,20):
        return "B","2º Turno"
    else:
        return "C","3º Turno"

def calcular_distancia(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return 999999
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))

def get_proxima_rota(turno_db, motorista):
    agora = datetime.now(TZ)
    hoje = agora.date()
    
    horarios = pd.read_sql_query("""
    SELECT locais.nome_local, horarios_rota.rota, horarios_rota.hora_chegada, 
           horarios_rota.hora_saida, horarios_rota.local_id
    FROM horarios_rota
    JOIN locais ON locais.id = horarios_rota.local_id
    WHERE turno=?
    ORDER BY hora_chegada
    """, conn, params=(turno_db,))
    
    if horarios.empty:
        return None
    
    cursor.execute("SELECT local_id FROM registros_rota WHERE motorista=? AND date(data_hora)=?", 
                   (motorista, hoje.strftime("%Y-%m-%d")))
    registrados_ids = {row[0] for row in cursor.fetchall()}
    
    for _, row in horarios.iterrows():
        if row['local_id'] not in registrados_ids:
            return {
                'nome_local': row['nome_local'],
                'hora_chegada': row['hora_chegada'],
                'hora_saida': row['hora_saida'],
                'local_id': row['local_id']
            }
    return None

def update_location():
    """Atualiza localização no session state"""
    try:
        from streamlit_geolocation import streamlit_geolocation
        location = streamlit_geolocation()
        if location:
            st.session_state.lat = location.get("latitude")
            st.session_state.lon = location.get("longitude")
            return True
    except:
        pass
    return False

def registrar_chegada(nome_local_registro, turno_db):
    cursor.execute("SELECT id FROM locais WHERE nome_local=?", (nome_local_registro,))
    local = cursor.fetchone()
    if not local:
        st.error("❌ Local não encontrado!")
        return
    
    local_id = local[0]
    agora = datetime.now(TZ)
    agora_str = agora.strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("SELECT hora_chegada FROM horarios_rota WHERE local_id=? AND turno=? AND hora_chegada IS NOT NULL",
                   (local_id, turno_db))
    previstos = cursor.fetchall()

    status = "SEM HORARIO"
    if previstos:
        menor_dif = None
        for p in previstos:
            h_prev = datetime.strptime(p[0].strip(), "%H:%M").replace(
                year=agora.year, month=agora.month, day=agora.day, tzinfo=TZ)
            dif = (agora - h_prev).total_seconds() / 60
            if menor_dif is None or abs(dif) < abs(menor_dif):
                menor_dif = dif
        
        if abs(menor_dif) <= TOLERANCIA_MINUTOS:
            status = "✅ NO HORARIO"
        elif menor_dif > 0:
            status = "⏰ ATRASADO"
        else:
            status = "🚀 ADIANTADO"

    cursor.execute("INSERT INTO registros_rota (motorista,local_id,data_hora,status) VALUES (?,?,?,?)",
                   (st.session_state.usuario, local_id, agora_str, status))
    conn.commit()
    
    st.session_state.ultimo_registro = agora
    st.success(f"🎉 **Registro OK!** {nome_local_registro} - {status}")
    st.rerun()

# =========================
# LOGIN
# =========================

if not st.session_state.logado:
    opcao = st.radio("🔐 Acesso", ["Login", "Criar Conta"])

    if opcao == "Login":
        col1, col2 = st.columns(2)
        with col1:
            usuario = st.text_input("👤 Usuário")
        with col2:
            senha = st.text_input("🔒 Senha", type="password")
        
        if st.button("🚀 Entrar", type="primary", use_container_width=True):
            cursor.execute("SELECT * FROM usuarios WHERE usuario=? AND senha=?", (usuario, senha))
            dados = cursor.fetchone()
            if dados:
                st.session_state.logado = True
                st.session_state.usuario = dados[1]
                st.session_state.tipo = dados[3]
                st.rerun()
            else:
                st.error("❌ Credenciais inválidas")

    if opcao == "Criar Conta":
        col1, col2 = st.columns(2)
        with col1:
            usuario = st.text_input("👤 Novo usuário")
            senha = st.text_input("🔒 Senha", type="password")
        with col2:
            tipo = st.selectbox("Tipo", ["motorista", "admin"])
            codigo = st.text_input("🔑 Código admin", type="password") if tipo == "admin" else CODIGO_ADMIN
        
        if st.button("💾 Cadastrar", type="primary", use_container_width=True):
            if tipo == "admin" and codigo != CODIGO_ADMIN:
                st.error("❌ Código inválido")
            else:
                cursor.execute("INSERT INTO usuarios(usuario,senha,tipo) VALUES(?,?,?)", (usuario, senha, tipo))
                conn.commit()
                st.success("✅ Conta criada!")

# =========================
# APLICAÇÃO PRINCIPAL
# =========================

else:
    st.sidebar.markdown(f"👤 **{st.session_state.usuario}**")
    st.sidebar.markdown(f"🔧 **{st.session_state.tipo.upper()}**")
    if st.sidebar.button("🚪 Sair"):
        st.session_state.logado = False
        st.rerun()

    # =========================
    # MOTORISTA
    # =========================
    if st.session_state.tipo == "motorista":
        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("🔄 Atualizar"):
                update_location()
                st.rerun()

        turno_db, turno_nome = turno_atual()
        proxima_rota = get_proxima_rota(turno_db, st.session_state.usuario)

        # PRÓXIMA ROTA
        col1, col2, col3 = st.columns([1, 3, 1])
        with col2:
            if proxima_rota:
                st.markdown(f"""
                <div style='background: linear-gradient(135deg, #4CAF50, #45a049); 
                           padding: 20px; border-radius: 15px; text-align: center; 
                           color: white; font-weight: bold; box-shadow: 0 8px 32px rgba(76,175,80,0.3);'>
                    <div style='font-size: 28px;'>🎯 PRÓXIMA</div>
                    <div style='font-size: 36px;'>{proxima_rota['nome_local']}</div>
                    <div style='font-size: 20px;'>🕐 {proxima_rota['hora_chegada']}</div>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div style='background: linear-gradient(135deg, #4CAF50, #45a049); 
                           padding: 20px; border-radius: 15px; text-align: center; 
                           color: white; font-weight: bold;'>
                    <div style='font-size: 32px;'>🎉 CONCLUÍDO!</div>
                </div>
                """, unsafe_allow_html=True)

        # LOCALIZAÇÃO
        st.subheader("📍 Localização")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("📍 CAPTURAR GPS", type="secondary", use_container_width=True):
                if update_location():
                    st.success("✅ GPS OK!")
                else:
                    st.error("❌ GPS falhou")
                st.rerun()
        
        lat = st.session_state.lat
        lon = st.session_state.lon

        if lat and lon:
            st.success(f"✅ {lat:.6f}, {lon:.6f}")

            locais_gps = {
                "ABE": (-23.0467087, -45.623646),
                "ABM": (-23.04783143066227, -45.62357453065028),
                "ABW": (-23.047105418124023, -45.625152508643936)
            }

            local_atual = None
            dist_min = float('inf')
            for nome, (lat_g, lon_g) in locais_gps.items():
                dist = calcular_distancia(lat, lon, lat_g, lon_g)
                if dist < dist_min:
                    dist_min = dist
                    local_atual = (nome, dist)

            if local_atual:
                nome_local, dist = local_atual
                col1, col2 = st.columns(2)
                with col1:
                    color = "normal" if dist <= 30 else "warning"
                    st.markdown(f"**{nome_local}**", unsafe_allow_html=True)
                
                st.metric("Distância", f"{dist:.0f}m")
            else:
                st.error("❌ Fora de área")
        else:
            st.warning("⚠️ Capture GPS")

        # BOTÃO REGISTRAR
        st.markdown("---")
        if lat and lon and local_atual and local_atual[1] <= 30:
            nome_local_registro, _ = local_atual
            
            agora = datetime.now(TZ)
            if st.session_state.ultimo_registro and (agora - st.session_state.ultimo_registro).seconds < 60:
                st.error("⏳ Aguarde 1min")
            else:
                col1, col2, col3 = st.columns([1,2,1])
                with col2:
                    if st.button(f"🚛 **REGISTRAR {nome_local_registro}** ✅", 
                               type="primary", use_container_width=True):
                        registrar_chegada(nome_local_registro, turno_db)
        else:
            st.error("❌ Aproxime-se (30m) + capture GPS")

        # Expanders
        with st.expander(f"📋 Rotas {turno_nome}"):
            horarios = pd.read_sql_query("""
            SELECT locais.nome_local, horarios_rota.* FROM horarios_rota 
            JOIN locais ON locais.id = horarios_rota.local_id WHERE turno=?
            ORDER BY hora_chegada
            """, conn, params=(turno_db,))
            st.dataframe(horarios, use_container_width=True)

        with st.expander("📊 Meus Registros"):
            hoje = datetime.now(TZ).date()
            registros = pd.read_sql_query("""
            SELECT locais.nome_local, registros_rota.data_hora, status 
            FROM registros_rota JOIN locais ON local_id = locais.id 
            WHERE motorista=? AND date(data_hora)=?
            ORDER BY data_hora DESC
            """, conn, params=(st.session_state.usuario, str(hoje)))
            st.dataframe(registros, use_container_width=True)

    # =========================
# ADMIN
# =========================

    if st.session_state.tipo=="admin":

        if st.button("🔄 Atualizar"):
            st.rerun()

        data_inicio, data_fim, data_label = filtro_data()

        st.header("Painel Administrativo")

        motoristas = pd.read_sql_query(
            "SELECT DISTINCT motorista FROM registros_rota",
            conn
        )

        lista_motoristas = ["Todos"] + motoristas["motorista"].dropna().tolist()

        motorista_filtro = st.selectbox("🚛 Filtrar por motorista", lista_motoristas)

        if motorista_filtro == "Todos":
            query = """
            SELECT locais.nome_local, registros_rota.data_hora,
            registros_rota.status, registros_rota.motorista
            FROM registros_rota
            JOIN locais ON registros_rota.local_id = locais.id
            WHERE data_hora BETWEEN ? AND ?
            ORDER BY data_hora DESC
            """
            params = (
                data_inicio.strftime("%Y-%m-%d %H:%M:%S"),
                data_fim.strftime("%Y-%m-%d %H:%M:%S")
            )
        else:
            query = """
            SELECT locais.nome_local, registros_rota.data_hora,
            registros_rota.status, registros_rota.motorista
            FROM registros_rota
            JOIN locais ON registros_rota.local_id = locais.id
            WHERE motorista=? AND data_hora BETWEEN ? AND ?
            ORDER BY data_hora DESC
            """
            params = (
                motorista_filtro,
                data_inicio.strftime("%Y-%m-%d %H:%M:%S"),
                data_fim.strftime("%Y-%m-%d %H:%M:%S")
            )

        registros = pd.read_sql_query(query, conn, params=params)

        st.dataframe(registros,use_container_width=True)

        with st.expander("📊 Dashboard de atrasos"):

            if not registros.empty:

                registros["data_hora"] = pd.to_datetime(registros["data_hora"], errors="coerce")

                registros["turno"] = registros["data_hora"].dt.hour.apply(
                lambda h:"1º Turno" if 6<=h<15
                else "2º Turno" if 15<=h<23
                else "3º Turno"
                )

                fig = px.histogram(
                registros,
                x="turno",
                color="status",
                barmode="group",
                text_auto=True
                )

                st.plotly_chart(fig,use_container_width=True)

        st.subheader("🛠️ Editor do Banco")

        tabela = st.selectbox(
            "Tabela",
            ["locais","horarios_rota","registros_rota","usuarios"]
        )

        df = pd.read_sql_query(f"SELECT * FROM {tabela}", conn)

        df_editado = st.data_editor(df,use_container_width=True,num_rows="dynamic")

        if st.button("💾 Salvar alterações"):

            cursor.execute(f"DELETE FROM {tabela}")

            for _, row in df_editado.iterrows():
                placeholders = ",".join(["?"] * len(row))
                cursor.execute(
                    f"INSERT INTO {tabela} VALUES ({placeholders})",
                    tuple(row)
                )

            conn.commit()
            st.success("Banco atualizado!")
