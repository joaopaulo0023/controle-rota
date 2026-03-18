import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, time
import cv2
import numpy as np
import plotly.express as px
from streamlit_geolocation import streamlit_geolocation
import math

# =========================
# CONFIG
# =========================

CODIGO_ADMIN = "123456"
TOLERANCIA_MINUTOS = 4

st.set_page_config(layout="wide")
st.title("🚛 Controle de Rotas")

# =========================
# SESSION STATE
# =========================

if "logado" not in st.session_state:
    st.session_state.logado = False

if "ultimo_registro" not in st.session_state:
    st.session_state.ultimo_registro = None

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
    hoje = datetime.now().date()
    data_escolhida = st.date_input("📅 Filtrar por data", value=hoje)
    data_inicio = datetime.combine(data_escolhida, time.min)
    data_fim = datetime.combine(data_escolhida, time.max)
    return data_inicio, data_fim, data_escolhida

def turno_atual():
    agora = datetime.now().time()
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

# =========================
# LOGIN
# =========================

if not st.session_state.logado:

    opcao = st.radio("Acesso",["Login","Criar Conta"])

    if opcao=="Login":

        usuario = st.text_input("Usuário")
        senha = st.text_input("Senha",type="password")

        if st.button("Entrar"):

            cursor.execute(
            "SELECT * FROM usuarios WHERE usuario=? AND senha=?",
            (usuario,senha))

            dados = cursor.fetchone()

            if dados:
                st.session_state.logado=True
                st.session_state.usuario=dados[1]
                st.session_state.tipo=dados[3]
                st.rerun()
            else:
                st.error("Usuário inválido")

    if opcao=="Criar Conta":

        usuario = st.text_input("Novo usuário")
        senha = st.text_input("Senha",type="password")
        tipo = st.selectbox("Tipo",["motorista","admin"])

        codigo=""

        if tipo=="admin":
            codigo = st.text_input("Código admin",type="password")

        if st.button("Cadastrar"):

            if tipo=="admin" and codigo!=CODIGO_ADMIN:
                st.error("Código admin inválido")
            else:
                cursor.execute(
                "INSERT INTO usuarios(usuario,senha,tipo) VALUES(?,?,?)",
                (usuario,senha,tipo))

                conn.commit()
                st.success("Conta criada")

# =========================
# SISTEMA
# =========================

else:

    st.sidebar.write("Usuário:",st.session_state.usuario)
    st.sidebar.write("Tipo:",st.session_state.tipo)

    if st.sidebar.button("Sair"):
        st.session_state.logado=False
        st.rerun()

# =========================
# MOTORISTA
# =========================

    if st.session_state.tipo=="motorista":

        if st.button("🔄 Atualizar"):
            st.rerun()

        data_inicio, data_fim, data_label = filtro_data()
        turno_db, turno_nome = turno_atual()

        # 🔥 ROTAS EM EXPANDER
        with st.expander(f"📍 Rotas do {turno_nome}", expanded=True):

            horarios = pd.read_sql_query("""
            SELECT locais.nome_local, horarios_rota.rota,
            horarios_rota.hora_chegada, horarios_rota.hora_saida
            FROM horarios_rota
            JOIN locais ON locais.id = horarios_rota.local_id
            WHERE turno=?
            ORDER BY hora_chegada
            """,conn,params=(turno_db,))

            st.dataframe(horarios,use_container_width=True)

        # 🔥 REGISTROS EM EXPANDER
        with st.expander(f"📋 Seus registros - {data_label}", expanded=True):

            registros_motorista = pd.read_sql_query("""
            SELECT locais.nome_local, registros_rota.data_hora, registros_rota.status
            FROM registros_rota
            JOIN locais ON locais.id = registros_rota.local_id
            WHERE motorista = ?
            AND data_hora BETWEEN ? AND ?
            ORDER BY data_hora DESC
            """, conn, params=(
                st.session_state.usuario,
                data_inicio.strftime("%Y-%m-%d %H:%M:%S"),
                data_fim.strftime("%Y-%m-%d %H:%M:%S")
            ))

            st.dataframe(registros_motorista, use_container_width=True)

        # =========================
        # LOCALIZAÇÃO
        # =========================

        st.subheader("📍 Sua localização")

        location = streamlit_geolocation()

        lat = location.get("latitude") if location else None
        lon = location.get("longitude") if location else None

        if lat is not None and lon is not None:
            st.success(f"Local capturado: {lat}, {lon}")
        else:
            st.warning("📍 Permita a localização e aguarde alguns segundos")

        # =========================
        # REGISTRO AUTOMÁTICO
        # =========================

        st.subheader("Registrar chegada")

        if lat is not None and lon is not None:

            locais_gps = {
                "ABE": (-23.045045045045043, -45.6228009218397),
                "ABM": (-23.04783143066227, -45.62357453065028),
                "ABW": (-23.047105418124023, -45.625152508643936)
            }

            local = None

            for nome_local, (LAT_GALPAO, LON_GALPAO) in locais_gps.items():

                distancia = calcular_distancia(lat, lon, LAT_GALPAO, LON_GALPAO)

                if distancia <= 30:

                    cursor.execute(
                        "SELECT id, nome_local FROM locais WHERE nome_local=?",
                        (nome_local,)
                    )

                    local = cursor.fetchone()
                    break

            if not local:
                st.error("❌ Você não está dentro de nenhum local permitido")
                st.stop()

            local_id = local[0]
            nome_local = local[1]

            agora = datetime.now()

            if st.session_state.ultimo_registro:
                if (agora - st.session_state.ultimo_registro).seconds < 60:
                    st.warning("Aguarde para registrar novamente")
                    st.stop()

            st.success(f"✅ Você está no {nome_local} - Registrando...")

            agora_str = agora.strftime("%Y-%m-%d %H:%M:%S")

            cursor.execute("""
            SELECT hora_chegada
            FROM horarios_rota
            WHERE local_id=? AND turno=? AND hora_chegada IS NOT NULL
            """,(local_id,turno_db))

            previstos = cursor.fetchall()

            status="SEM HORARIO"

            if previstos:

                menor_dif = None

                for p in previstos:
                    h_prev = datetime.strptime(p[0].strip(), "%H:%M")
                    h_prev = h_prev.replace(
                        year=agora.year,
                        month=agora.month,
                        day=agora.day
                    )

                    dif = (agora - h_prev).total_seconds() / 60

                    if menor_dif is None or abs(dif) < abs(menor_dif):
                        menor_dif = dif

                if abs(menor_dif) <= TOLERANCIA_MINUTOS:
                    status = "NO HORARIO"
                elif menor_dif > 0:
                    status = "ATRASADO"
                else:
                    status = "ADIANTADO"

            cursor.execute("""
            INSERT INTO registros_rota
            (motorista,local_id,data_hora,status)
            VALUES (?,?,?,?)
            """,
            (st.session_state.usuario,local_id,agora_str,status))

            conn.commit()

            st.session_state.ultimo_registro = agora

            st.success(f"✔ Registro salvo no {nome_local} - {status}")
            st.rerun()
# =========================
# ADMIN
# =========================

    if st.session_state.tipo=="admin":

        if st.button("🔄 Atualizar"):
            st.rerun()

        data_inicio, data_fim, data_label = filtro_data()

        st.header("Painel Administrativo")

        # 🔥 BUSCAR MOTORISTAS
        motoristas = pd.read_sql_query(
            "SELECT DISTINCT motorista FROM registros_rota",
            conn
        )

        lista_motoristas = ["Todos"] + motoristas["motorista"].dropna().tolist()

        motorista_filtro = st.selectbox("🚛 Filtrar por motorista", lista_motoristas)

        # 🔥 QUERY DINÂMICA
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

        # 🔥 DASHBOARD FILTRADO
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

        # =========================
        # EDITOR
        # =========================

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
