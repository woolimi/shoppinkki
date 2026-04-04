from setuptools import setup

package_name = 'control_service'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='woolim',
    maintainer_email='woolim@example.com',
    description='ShopPinkki control service',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'main = control_service.main:main',
        ],
    },
)
