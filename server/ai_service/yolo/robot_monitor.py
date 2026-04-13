import streamlit as st
import socket
import struct
import numpy as np
import cv2
import time
import os
import json

st.set_page_config(page_title="Pinky Pro - Live Monitor", layout="wide")

st.title("👁️ Eyes of Pinky: Live Monitor")

# ── Sidebar ──────────────────────────────────────────────────────────────────
st.sidebar.header("📡 Connection")
robot_ip = st.sidebar.text_input("Robot IP Address", "127.0.0.1")
robot_port = 5007

# AI Server Health Check (on Joey)
st.sidebar.markdown("---")
st.sidebar.subheader("🧠 Local AI Server Status")
try:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        if s.connect_ex(('127.0.0.1', 5005)) == 0:
            st.sidebar.success("✅ AI Server is RUNNING")
        else:
            st.sidebar.error("❌ AI Server is STOPPED")
except:
    st.sidebar.error("❌ AI Server Check Failed")

st.sidebar.markdown("---")
st.sidebar.header("🧠 AI Model Control")

# 1. 모델 리스트 가져오기
_script_dir = os.path.dirname(os.path.abspath(__file__))
models_dir = os.path.join(_script_dir, 'models')
config_path = os.path.join(_script_dir, 'active_model.json')

if os.path.exists(models_dir):
    model_files = sorted([f for f in os.listdir(models_dir) if f.endswith('.pt')])
    # Debug: Print found models to help user verify
    # print(f"DEBUG: Found models in {models_dir}: {model_files}")
else:
    model_files = []

# 2. 현재 모델/신뢰도 로드
current_config = {"active_model": "", "confidence": 0.25}
if os.path.exists(config_path):
    try:
        with open(config_path, 'r') as f:
            current_config = json.load(f)
    except: pass

# 3. 모델 선택 UI
selected_model = st.sidebar.selectbox(
    "Select YOLO Model", 
    model_files, 
    index=model_files.index(current_config.get("active_model")) if current_config.get("active_model") in model_files else 0
)

# 4. 신뢰도 슬라이더
conf_value = st.sidebar.slider(
    "Detection Confidence", 
    min_value=0.01, 
    max_value=1.0, 
    value=float(current_config.get("confidence", 0.25)),
    step=0.01
)

# 5. 설정 업데이트 로직
if (selected_model != current_config.get("active_model") or 
    conf_value != current_config.get("confidence")):
    
    new_config = {
        "active_model": selected_model,
        "confidence": conf_value
    }
    with open(config_path, 'w') as f:
        json.dump(new_config, f, indent=4)
    st.sidebar.success(f"Config updated: {selected_model} ({conf_value})")

# ── Main UI ──────────────────────────────────────────────────────────────────
st.sidebar.markdown("---")
st.sidebar.subheader("📺 Display Settings")
swap_colors = st.sidebar.checkbox("🔄 Swap Blue/Red Channels", value=False)

status_placeholder = st.sidebar.empty()
frame_placeholder = st.empty()

# 세션 상태 초기화
if 'connected' not in st.session_state:
    st.session_state.connected = False

connect_btn = st.sidebar.button("🔌 Connect to Robot" if not st.session_state.connected else "🛑 Disconnect")

if connect_btn:
    st.session_state.connected = not st.session_state.connected

if st.session_state.connected:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect((robot_ip, robot_port))
        status_placeholder.success(f"Connected to {robot_ip}:{robot_port}")
        
        # Stop 버튼을 사이드바에 추가하여 루프를 제어할 수 있게 함
        while st.session_state.connected:
            # 1. Read size (4 bytes)
            size_data = sock.recv(4)
            if not size_data:
                break
            size = struct.unpack("!I", size_data)[0]
            
            # 2. Read frame bytes
            data = b""
            while len(data) < size:
                packet = sock.recv(size - len(data))
                if not packet:
                    break
                data += packet
            
            # 3. Decode JPEG
            nparr = np.frombuffer(data, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if frame is not None:
                # 🔄 Real-time Color Swap
                if swap_colors:
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                
                frame_placeholder.image(frame, caption=f"Live feed from {robot_ip}", use_container_width=True)
            
            # Small sleep to allow UI interaction
            time.sleep(0.01)

    except Exception as e:
        status_placeholder.error(f"Connection failed: {e}")
        st.session_state.connected = False
    finally:
        if 'sock' in locals():
            sock.close()
else:
    st.info(f"Enter the Robot IP (currently {robot_ip}) and click Connect.")

st.sidebar.markdown("---")
st.sidebar.subheader("How to use")
st.sidebar.write("1. Start `yolo_server.py` on your laptop.")
st.sidebar.write("2. Start your robot and ensure it points to your laptop IP.")
st.sidebar.write("3. Enter the Robot's IP above and Connect.")
