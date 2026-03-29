#!/usr/bin/env python3
import threading
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String
from flask import Flask, Response

app = Flask(__name__)
latest_jpeg = None
ros_node = None

class WebViewerNode(Node):
    def __init__(self):
        super().__init__('web_viewer_node')
        self.declare_parameter('port', 5002)
        self.sub = self.create_subscription(CompressedImage, '/tracker/debug_image/compressed', self._cb_image, 1)
        self.pub_cmd = self.create_publisher(String, '/tracker/command', 10)
        self.get_logger().info("🌐 WEB VIEWER READY")

    def _cb_image(self, msg):
        global latest_jpeg
        latest_jpeg = bytes(msg.data)

    def send_command(self, cmd):
        msg = String()
        msg.data = cmd
        self.pub_cmd.publish(msg)

def _generate_frames():
    while True:
        if latest_jpeg is not None:
            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + latest_jpeg + b'\r\n')
        import time
        time.sleep(1.0 / 30.0)

@app.route('/video_feed')
def video_feed():
    return Response(_generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/')
def index():
    return """
    <html><head><title>Offload Viewer</title>
    <style>body { background: #111; color: #fff; text-align: center; font-family: Arial; }
    img { max-width: 100%; border: 3px solid #00ffcc; border-radius: 10px; margin-top: 20px; }
    button { padding: 15px 30px; font-size: 18px; margin: 10px; cursor: pointer; border-radius: 8px; background: #222; color: #00ffcc; border: 2px solid #00ffcc; font-weight: bold; }
    button:hover { background: #00ffcc; color: #111; }
    .clear-btn { color: #ff6b6b; border-color: #ff6b6b; }
    .clear-btn:hover { background: #ff6b6b; color: #111; }
    </style></head><body>
    <h1>🤖 PC Offload Tracker</h1>
    <div><button onclick="fetch('/api/calibrate')">📸 캘리브레이션 시작</button><button class="clear-btn" onclick="fetch('/api/clear')">🗑️ 소유자 초기화</button></div>
    <img src="/video_feed">
    </body></html>
    """

@app.route('/api/calibrate')
def api_calibrate():
    if ros_node: ros_node.send_command("calibrate")
    return "OK"

@app.route('/api/clear')
def api_clear():
    if ros_node: ros_node.send_command("clear")
    return "OK"

def main(args=None):
    global ros_node
    rclpy.init(args=args)
    ros_node = WebViewerNode()
    port = ros_node.get_parameter('port').value
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False), daemon=True).start()
    try:
        rclpy.spin(ros_node)
    except KeyboardInterrupt:
        pass
    finally:
        ros_node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
