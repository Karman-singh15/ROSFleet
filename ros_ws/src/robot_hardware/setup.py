## Lets `import robot_hardware.esp32_link` work from any node in the workspace.
## Do NOT run this file directly - catkin calls it via catkin_python_setup().
from distutils.core import setup
from catkin_pkg.python_setup import generate_distutils_setup

setup(**generate_distutils_setup(
    packages=['robot_hardware'],
    package_dir={'': 'src'},
))
