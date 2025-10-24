"""
Setup script for signal-recorder package
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read README for long description
readme_file = Path(__file__).parent / "README.md"
long_description = readme_file.read_text() if readme_file.exists() else ""

setup(
    name="signal-recorder",
    version="0.1.0",
    author="Signal Recorder Project",
    author_email="",
    description="Automated recording and upload system for ka9q-radio streams",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/signal-recorder",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Science/Research",
        "Topic :: Scientific/Engineering",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    python_requires=">=3.10",
    install_requires=[
        "toml>=0.10.2",
        "numpy>=1.24.0",
        "soundfile>=0.12.0",
        "digital_rf>=2.6.0",
        "zeroconf>=0.132.0",  # For mDNS discovery
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-cov>=4.0.0",
            "black>=23.0.0",
            "flake8>=6.0.0",
            "mypy>=1.0.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "signal-recorder=signal_recorder.cli:main",
        ],
    },
)

