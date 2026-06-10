from setuptools import setup, find_packages

setup(
    name="project-echo",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "textual>=0.80.0",
        "httpx>=0.27.0",
        "rich>=13.0.0",
    ],
    entry_points={
        "console_scripts": [
            "echo=echo.__main__:main",
        ],
    },
    python_requires=">=3.10",
)
