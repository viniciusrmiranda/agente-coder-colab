import streamlit as st
import sqlite3
from groq import Groq
from duckduckgo_search import DDGS
import pypdf
import uuid
import re
from sentence_transformers import SentenceTransformer
import numpy as np
import json

st.set_page_config(page_title="Agente Coder", page_icon="🤖", layout="wide")

# --- AUTENTICAÇÃO COM GOOGLE ---
if not st.user.is_logged_in:
    st.title("🤖 Agente Coder")
    st.write("Faça login com sua conta do Google para acessar a aplicação.")
    if st.button("🔑 Entrar com o Google"):
        st.login("google")
    st.stop()

user_email = st.user.email

# --- CARREGAR MODELO DE EMBEDDING (LOCAL) ---
@st.cache_resource
def load_embedder():
    return SentenceTransformer('all-MiniLM-L6-v2')

embedder = load_embedder()

# --- BANCO DE DADOS COM MEMÓRIA ---
def init_db():
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    
    # Conversas
    c.execute('''CREATE TABLE IF NOT EXISTS conversas 
                 (chat_id TEXT PRIMARY KEY, user_email TEXT, titulo TEXT, 
                  criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Histórico
    c.execute('''CREATE TABLE IF NOT EXISTS historico 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT, user_email TEXT, role TEXT, content TEXT)''')
    
    # Memórias (com embedding armazenado como JSON)
    c.execute('''CREATE TABLE IF NOT EXISTS memorias 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_email TEXT, fato TEXT, embedding TEXT, criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    conn.commit()
    conn.close()

def listar_conversas(email):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("SELECT chat_id, titulo FROM conversas WHERE user_email = ? ORDER BY criado_em DESC", (email,))
    rows = c.fetchall()
    conn.close()
    return rows

def criar_nova_conversa(email, titulo="Nova Conversa"):
    chat_id = str(uuid.uuid4())
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("INSERT INTO conversas (chat_id, user_email, titulo) VALUES (?, ?, ?)", (chat_id, email, titulo))
    conn.commit()
    conn.close()
    return chat_id

def atualizar_titulo_conversa(chat_id, texto):
    titulo = texto[:30] + "..." if len(texto) > 30 else texto
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("UPDATE conversas SET titulo = ? WHERE chat_id = ? AND titulo = 'Nova Conversa'", (titulo, chat_id))
    conn.commit()
    conn.close()

def salvar_mensagem(chat_id, email, role, content):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("INSERT INTO historico (chat_id, user_email, role, content) VALUES (?, ?, ?, ?)", (chat_id, email, role, content))
    conn.commit()
    conn.close()

def carregar_historico_chat(chat_id):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("SELECT role, content FROM historico WHERE chat_id = ? ORDER BY id ASC", (chat_id,))
    rows = c.fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1]} for r in rows]

def deletar_conversa(chat_id):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("DELETE FROM conversas WHERE chat_id = ?", (chat_id,))
    c.execute("DELETE FROM historico WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()

# --- FUNÇÕES DE MEMÓRIA ---
def salvar_memoria(email, fato):
    """Salva um fato na memória com embedding."""
    if not fato or len(fato) < 5:
        return
    embedding = embedder.encode(fato).tolist()
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("INSERT INTO memorias (user_email, fato, embedding) VALUES (?, ?, ?)", 
              (email, fato, json.dumps(embedding)))
    conn.commit()
    conn.close()

def buscar_memorias(email, query, limit=3):
    """Busca memórias relevantes usando similaridade de cosseno."""
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("SELECT id, fato, embedding FROM memorias WHERE user_email = ? ORDER BY criado_em DESC", (email,))
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        return []
    
    query_embedding = embedder.encode(query)
    resultados = []
    for id, fato, emb_json in rows:
        emb = np.array(json.loads(emb_json))
        sim = np.dot(query_embedding, emb) / (np.linalg.norm(query_embedding) * np.linalg.norm(emb) + 1e-8)
        resultados.append((sim, fato))
    
    resultados.sort(key=lambda x: x[0], reverse=True)
    return [fato for _, fato in resultados[:limit]]

# --- EXTRAÇÃO DE MEMÓRIAS USANDO GROQ ---
def extrair_memorias_automatico(texto, email, api_key):
    """Usa o Groq para extrair fatos da mensagem do usuário."""
    # Lista de modelos gratuitos para extração (fallback)
    modelos_extracao = [
        "openai/gpt-oss-20b",
        "llama-3.1-8b-instant",
        "mixtral-8x7b-32768",
        "gemma2-9b-it"
    ]
    
    prompt = f"""
    Analise a mensagem do usuário abaixo e extraia fatos importantes sobre ele (nome, interesses, profissão, projetos, habilidades, etc.).
    Retorne APENAS uma lista de fatos, um por linha, sem numeração ou formatação extra.
    Se não houver fatos relevantes, retorne a palavra "NENHUM".
    
    Mensagem: "{texto}"
    """
    
    for model in modelos_extracao:
        try:
            client = Groq(api_key=str(api_key).strip())
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": "Você é um assistente especializado em extrair fatos de conversas."},
                          {"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=200,
            )
            resultado = response.choices[0].message.content.strip()
            if resultado and resultado != "NENHUM":
                for linha in resultado.split('\n'):
                    fato = linha.strip()
                    if fato and len(fato) > 5:
                        salvar_memoria(email, fato)
                        st.toast(f"🧠 Memória salva: {fato[:50]}...", icon="✅")
                return  # Sai após o primeiro sucesso
        except Exception:
            continue  # Tenta o próximo modelo

init_db()

# --- VALIDAR GROQ API KEY ---
api_key = st.secrets.get("GROQ_API_KEY")
if not api_key:
    st.error("❌ GROQ_API_KEY não configurada nos Secrets do Streamlit.")
    st.info("Por favor, configure sua chave de API da Groq em: Settings → Secrets → GROQ_API_KEY = 'sua_chave_aqui'")
    st.stop()

# Testar a chave de API com uma chamada simples
try:
    test_client = Groq(api_key=str(api_key).strip())
    test_client.models.list()  # Verifica se a chave é válida
except Exception as e:
    st.error(f"❌ Erro na chave de API da Groq: {e}")
    st.info("Verifique se a chave está correta e ativa no console da Groq.")
    st.stop()

# --- MODELO PRINCIPAL (com fallback) ---
modelos_principais = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "llama-3.1-8b-instant",
    "mixtral-8x7b-32768",
    "gemma2-9b-it"
]
active_model = modelos_principais[0]  # Será substituído pelo primeiro que funcionar

# --- GERENCIAMENTO DE SESSÃO ---
if "active_chat_id" not in st.session_state:
    st.session_state.active_chat_id = None

# --- SIDEBAR ---
with st.sidebar:
    st.title("📋 Conversas")
    if st.button("➕ Nova Conversa", use_container_width=True):
        novo_id = criar_nova_conversa(user_email)
        st.session_state.active_chat_id = novo_id
        st.rerun()
    
    st.markdown("---")
    conversas = listar_conversas(user_email)
    if not conversas:
        st.info("Nenhuma conversa encontrada.")
    else:
        for chat_id, titulo in conversas:
            col1, col2 = st.columns([0.8, 0.2])
            with col1:
                if st.button(f"{titulo}", key=f"chat_{chat_id}", use_container_width=True):
                    st.session_state.active_chat_id = chat_id
                    st.rerun()
            with col2:
                if st.button("🗑️", key=f"del_{chat_id}"):
                    deletar_conversa(chat_id)
                    st.rerun()
    
    st.sidebar.markdown("---")
    
    # Exibir memórias salvas
    st.sidebar.subheader("🧠 Memórias")
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("SELECT fato FROM memorias WHERE user_email = ? ORDER BY criado_em DESC LIMIT 10", (user_email,))
    memorias = c.fetchall()
    conn.close()
    if memorias:
        for mem in memorias:
            st.sidebar.write(f"- {mem[0]}")
    else:
        st.sidebar.info("Nenhuma memória salva ainda.")
    
    st.sidebar.markdown("---")
    st.sidebar.write(f"🔑 Conectado como: {user_email}")
    if st.sidebar.button("🚪 Sair"):
        st.logout()

# --- ÁREA PRINCIPAL ---
if not st.session_state.active_chat_id:
    st.session_state.active_chat_id = criar_nova_conversa(user_email)

st.title("🤖 Agente Coder")

messages = carregar_historico_chat(st.session_state.active_chat_id)
for msg in messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

chat_prompt = st.chat_input("Digite sua mensagem...")

if chat_prompt:
    # Salvar mensagem do usuário
    salvar_mensagem(st.session_state.active_chat_id, user_email, "user", chat_prompt)
    atualizar_titulo_conversa(st.session_state.active_chat_id, chat_prompt)
    
    with st.chat_message("user"):
        st.markdown(chat_prompt)
    
    # Extrair memórias automaticamente (usa Groq)
    extrair_memorias_automatico(chat_prompt, user_email, api_key)
    
    # Buscar memórias relevantes para a pergunta
    memorias_relevantes = buscar_memorias(user_email, chat_prompt, limit=3)
    texto_memorias = "\n".join([f"- {mem}" for mem in memorias_relevantes]) if memorias_relevantes else "Nenhuma memória relevante encontrada."
    
    # Gerar resposta (tenta cada modelo até um funcionar)
    with st.chat_message("assistant"):
        with st.spinner("Pensando..."):
            resposta_gerada = False
            for model in modelos_principais:
                try:
                    client = Groq(api_key=str(api_key).strip())
                    
                    system_prompt = f"""Você é um assistente especialista em programação, baseado no modelo da Groq.
                    
                    MEMÓRIAS SOBRE O USUÁRIO (extraídas automaticamente):
                    {texto_memorias}
                    
                    Use essas memórias para personalizar suas respostas. Seja natural e direto."""
                    
                    historico = carregar_historico_chat(st.session_state.active_chat_id)
                    messages_api = [{"role": "system", "content": system_prompt}] + historico
                    
                    chat_completion = client.chat.completions.create(
                        model=model,
                        messages=messages_api
                    )
                    bot_reply = chat_completion.choices[0].message.content
                    st.markdown(bot_reply)
                    
                    # Salvar resposta
                    salvar_mensagem(st.session_state.active_chat_id, user_email, "assistant", bot_reply)
                    resposta_gerada = True
                    break  # Sai do loop se funcionou
                except Exception as err:
                    continue  # Tenta o próximo modelo
            
            if not resposta_gerada:
                st.error("⚠️ Nenhum modelo disponível funcionou. Verifique sua chave de API ou tente novamente mais tarde.")
