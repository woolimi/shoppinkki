import os
from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
    return LaunchDescription([
        Node(
            package='pinky_offload_vision',
            executable='server_tracker',
            name='server_tracker_node',
            output='screen',
            parameters=[{
                'imgsz': 640,
                'reid_threshold': 0.55,
                'tracking_threshold': 0.45,
                'reid_confirm_frames': 3,
                'jpeg_quality': 80,
            }],
        ),
        Node(
            package='pinky_offload_vision',
            executable='web_viewer',
            name='web_viewer_node',
            output='screen',
            parameters=[{'port': 5002}],
        ),
    ])
