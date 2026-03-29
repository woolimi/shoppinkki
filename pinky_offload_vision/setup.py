from setuptools import find_packages, setup
import os

package_name = 'pinky_offload_vision'

setup(
    name=package_name,
    version='0.0.0',
    packages=['pinky_offload_vision', 'pinky_offload_vision.common'],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), ['launch/offload.launch.py']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='pinky',
    maintainer_email='pinky@todo.todo',
    description='TODO: Package description',
    license='TODO: License declaration',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'server_tracker = pinky_offload_vision.server_tracker:main',
            'web_viewer = pinky_offload_vision.web_viewer:main',
        ],
    },
)
