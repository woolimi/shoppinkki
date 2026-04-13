import streamlit as st
import os
import json
import time
from PIL import Image
from ultralytics import YOLO
import cv2
import numpy as np

# ── Configuration ────────────────────────────────────────────────────────────
_script_dir = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(_script_dir, 'models')
CONFIG_PATH = os.path.join(_script_dir, 'active_model.json')

# ── Page Setup ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="YOLO Model Playground",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom Styling ───────────────────────────────────────────────────────────
st.markdown("""
    <style>
    .main {
        background-color: #0e1117;
    }
    .stButton>button {
        width: 100%;
        border-radius: 5px;
        height: 3em;
        background-color: #2e7bcf;
        color: white;
        border: none;
    }
    .stButton>button:hover {
        background-color: #3d8ced;
    }
    .model-card {
        padding: 20px;
        border-radius: 10px;
        background: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.1);
        margin-bottom: 15px;
    }
    .active-badge {
        background-color: #28a745;
        color: white;
        padding: 4px 8px;
        border-radius: 4px;
        font-size: 0.8em;
    }
    </style>
""", unsafe_allow_html=True)

# ── Helpers ──────────────────────────────────────────────────────────────────
def get_model_files():
    if not os.path.exists(MODELS_DIR):
        return []
    return [f for f in os.listdir(MODELS_DIR) if f.endswith('.pt')]

def get_active_model():
    if not os.path.exists(CONFIG_PATH):
        return None
    try:
        with open(CONFIG_PATH, 'r') as f:
            return json.load(f).get('active_model')
    except:
        return None

def set_active_model(model_name):
    with open(CONFIG_PATH, 'r+') if os.path.exists(CONFIG_PATH) else open(CONFIG_PATH, 'w+') as f:
        try:
            data = json.load(f)
        except:
            data = {}
        data['active_model'] = model_name
        f.seek(0)
        json.dump(data, f)
        f.truncate()

@st.cache_resource
def load_yolo_model(path):
    model = YOLO(path)
    return model

def process_image(model, img_pil, conf):
    # Pass PIL image directly to YOLO for best compatibility
    results = model(img_pil, conf=conf, verbose=False)
    
    if not results or len(results) == 0:
        return None, 0, [], "Unknown", {}
        
    r = results[0]
    res_plotted = r.plot()
    task = getattr(model, 'task', 'detect')
    
    detections = []
    
    # Unified counting: boxes > masks > keypoints
    count = 0
    if hasattr(r, 'boxes') and r.boxes is not None:
        count = len(r.boxes)
    elif hasattr(r, 'masks') and r.masks is not None:
        count = len(r.masks)
    elif hasattr(r, 'keypoints') and r.keypoints is not None:
        count = len(r.keypoints)
    
    # Extract data for the table
    if count > 0:
        for i in range(count):
            conf_val = 0.0
            cls_name = "Unknown"
            
            # Try to get class/conf from boxes (works for -seg and -pose too)
            if hasattr(r, 'boxes') and r.boxes is not None and len(r.boxes) > i:
                conf_val = float(r.boxes[i].conf[0])
                cls_id = int(r.boxes[i].cls[0])
                cls_name = model.names.get(cls_id, f"ID:{cls_id}")
            elif hasattr(r, 'probs') and r.probs is not None:
                conf_val = float(r.probs.top1conf)
                cls_name = model.names.get(int(r.probs.top1), "Classic")
            
            detections.append({
                "Index": i,
                "Class": cls_name,
                "Confidence": round(conf_val, 4),
            })
            
    # Debug info for developer
    debug_data = {
        "Has Boxes": hasattr(r, 'boxes') and r.boxes is not None,
        "Boxes Count": len(r.boxes) if hasattr(r, 'boxes') and r.boxes is not None else 0,
        "Has Masks": hasattr(r, 'masks') and r.masks is not None,
        "Masks Count": len(r.masks) if hasattr(r, 'masks') and r.masks is not None else 0,
        "Model Names": model.names
    }
            
    return res_plotted, count, detections, task, debug_data

# ── Sidebar ──────────────────────────────────────────────────────────────────
st.sidebar.title("🛠️ Controller")
models = get_model_files()
active_model = get_active_model()

st.sidebar.subheader("Model Selection")
selected_model_name = st.sidebar.selectbox("Select Model to Test", models)
conf_threshold = st.sidebar.slider("Confidence Threshold", 0.0, 1.0, 0.25, 0.05)

if st.sidebar.button("🚀 Deploy to Robot"):
    set_active_model(selected_model_name)
    st.sidebar.success(f"Deployed {selected_model_name}!")
    time.sleep(1)
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.subheader("Model Info")
if selected_model_name:
    temp_model = load_yolo_model(os.path.join(MODELS_DIR, selected_model_name))
    st.sidebar.write(f"**Task:** {temp_model.task}")
    st.sidebar.write(f"**Classes:** {len(temp_model.names)}")
    with st.sidebar.expander("Show Class List"):
        st.write(temp_model.names)

st.sidebar.markdown("---")
st.sidebar.info(f"**Current Active Model:** \n\n {active_model or 'None'}")

# ── Main UI ──────────────────────────────────────────────────────────────────
st.title("🛡️ YOLO Model Playground")
st.markdown("Compare and test your YOLO models before deploying them to the Pinky Pro.")

col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("📸 Input Image")
    uploaded_file = st.file_uploader("Upload an image for testing...", type=['jpg', 'jpeg', 'png'])
    
    # Example Image if none uploaded
    if uploaded_file is None:
        st.info("Upload an image to start testing.")
        # Create a placeholder black image
        image = Image.new('RGB', (640, 480), color=(30, 30, 30))
    else:
        image = Image.open(uploaded_file)
    
    st.image(image, caption="Original Image", use_container_width=True)

with col2:
    st.subheader("🔍 Detection Results")
    
    if selected_model_name:
        with st.spinner(f"Running {selected_model_name}..."):
            model_path = os.path.join(MODELS_DIR, selected_model_name)
            model = load_yolo_model(model_path)
            
            # Use PIL image directly
            processed_img, count, detections, task, debug_data = process_image(model, image, conf_threshold)
            
            if processed_img is not None:
                st.image(processed_img, caption=f"Result ({task}): {selected_model_name}", use_container_width=True)
                
                # Metrics Row
                m_col1, m_col2, m_col3 = st.columns(3)
                m_col1.metric("Total Detections", count)
                if count > 0:
                    avg_conf = sum(d['Confidence'] for d in detections) / len(detections) if detections else 0
                    m_col2.metric("Avg Confidence", f"{avg_conf:.2f}")
                
                if count > 0:
                    st.subheader("📋 Detection Details")
                    st.dataframe(detections, use_container_width=True, hide_index=True)
                else:
                    st.info(f"No {task} targets found with current settings.")

                with st.expander("🛠️ Developer Debug Info (JSON)"):
                    st.json(debug_data)
            
            if selected_model_name == active_model:
                st.success("✨ This model is currently ACTIVE on the robot.")
            else:
                st.warning("⚠️ This model is NOT active on the robot.")

# ── Comparison View (Optional) ──────────────────────────────────────────────
with st.expander("⚖️ Side-by-Side Comparison"):
    comp_col1, comp_col2 = st.columns(2)
    
    m1_name = comp_col1.selectbox("Model A", models, index=0)
    m2_name = comp_col2.selectbox("Model B", models, index=min(1, len(models)-1))
    
    if uploaded_file:
        # Model A
        m1 = load_yolo_model(os.path.join(MODELS_DIR, m1_name))
        img_a, count_a, _, task_a, _ = process_image(m1, image, conf_threshold)
        if img_a is not None:
            comp_col1.image(img_a, use_container_width=True)
            comp_col1.metric(f"{m1_name} ({task_a})", count_a)
        
        # Model B
        m2 = load_yolo_model(os.path.join(MODELS_DIR, m2_name))
        img_b, count_b, _, task_b, _ = process_image(m2, image, conf_threshold)
        if img_b is not None:
            comp_col2.image(img_b, use_container_width=True)
            comp_col2.metric(f"{m2_name} ({task_b})", count_b)
