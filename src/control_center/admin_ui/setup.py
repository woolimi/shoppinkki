from setuptools import find_packages, setup
import os
from glob import glob

package_name = 'admin_ui'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'assets'),
            glob('assets/*')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='shoppinkki',
    maintainer_email='admin@shoppinkki.local',
    description='ShopPinkki Admin UI — PyQt6 데스크톱 관제 앱',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'admin_ui = admin_ui.main:main',
        ],
    },
)
