# Camera Agent System

This project implements a camera agent using SPADE (Smart Python Agent Development Environment) that can capture and send photos upon request through XMPP communication using an external USB camera.

## Prerequisites

- Docker and Docker Compose installed
- A working webcam connected to your system
- Linux system with video device access (typically /dev/video*)

## Installation & Running

1. Clone this repository:
```bash
git clone https://github.com/dij0s/AB2camera
cd AB2camera
```

2. Start the application:
```bash
docker-compose up
```

The camera agent will start and wait for photo requests through XMPP.

## System Architecture

- Uses XMPP for communication (Prosody server)
- OpenCV for camera capture
- SPADE framework for agent implementation
