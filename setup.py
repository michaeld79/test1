from setuptools import setup, find_packages

setup(
    name="revtui",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "textual>=0.82.0",
        "click>=8.0.0",
        "gitpython>=3.1.0",
    ],
    entry_points={
        "console_scripts": [
            "revtui=revtui.cli:main",
        ],
    },
    python_requires=">=3.10",
)
