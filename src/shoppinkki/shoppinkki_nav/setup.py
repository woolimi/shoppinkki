from setuptools import find_packages, setup
import os
from glob import glob

package_name = 'shoppinkki_nav'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'config'),
            glob('config/*.yaml')),
        (os.path.join('share', package_name, 'launch'),
            glob('launch/*.py')),
        (os.path.join('share', package_name, 'maps'),
            glob('maps/*')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='woolim',
    maintainer_email='woolim@example.com',
    description='ShopPinkki navigation: BT1~BT5 + BoundaryMonitor + Nav2 config',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'boundary_monitor = shoppinkki_nav.boundary_monitor:main',
        ],
    },
)
