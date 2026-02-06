FROM node:22-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    git \
    procps \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/bin/python3 /usr/bin/python

RUN npm install -g @google/gemini-cli

RUN useradd -m -s /bin/bash coder
USER coder
WORKDIR /workspace
