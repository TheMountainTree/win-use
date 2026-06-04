from setuptools import setup, find_packages

setup(
    name="win-use",
    version="0.2.0",
    packages=find_packages(),
    install_requires=[
        "uiautomation>=2.0",
        "typer>=0.9",
        "Pillow>=9.0",
        "pyautogui",
        "pyperclip",
    ],
    extras_require={
        "vision": ["openai>=1.0"],
    },
    entry_points={
        "console_scripts": [
            "win-use=win_use.cli:main",
        ],
    },
    python_requires=">=3.10",
    author="TheMountainTree",
    description="Windows Computer Use CLI — 让 AI Agent 操控 Windows 桌面",
    classifiers=[
        "Programming Language :: Python :: 3.10",
        "Operating System :: Microsoft :: Windows",
    ],
)
