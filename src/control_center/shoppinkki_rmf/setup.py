from setuptools import find_packages, setup

package_name = 'shoppinkki_rmf'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
         [f'resource/{package_name}']),
        (f'share/{package_name}', ['package.xml']),
        (f'share/{package_name}/launch', ['launch/rmf_fleet.launch.py']),
        (f'share/{package_name}/config', ['config/fleet_config.yaml']),
        (f'share/{package_name}/maps', [
            'maps/shop.building.yaml',
            'maps/shop_nav_graph.yaml',
        ]),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='woolim',
    maintainer_email='woolim@example.com',
    description='ShopPinkki Open-RMF Fleet Adapter',
    license='MIT',
    entry_points={
        'console_scripts': [
            'fleet_adapter = shoppinkki_rmf.fleet_adapter:main',
        ],
    },
)
