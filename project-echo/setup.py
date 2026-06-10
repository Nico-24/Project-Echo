from setuptools import setup, find_packages

setup(
    name="project-echo",
    version="1.0.0",
    description="Project Echo - a terminal UI coding assistant for local LLMs",
    author="Nico",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "textual>=0.80.0",
        "httpx>=0.27.0",
    ],
    entry_points={
        "console_scripts": [
            "pe = echo.__main__:main",
            "pecho = echo.__main__:main",
            "project-echo = echo.__main__:main",
        ],
    },
)
