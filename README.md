# Battery Management System

A smart home battery management system that optimizes charging and discharging cycles based on household power consumption.

## Overview

This project provides an intelligent control system for a home battery setup that:

1. Monitors real-time power consumption from Shelly power meters
2. Communicates with a battery management system (JKBMS) to monitor battery health and status
3. Controls a Soyo inverter for discharging power from the battery when needed
4. Manages charging pins through GPIO connections on a Raspberry Pi
5. Optimizes charging during low-consumption periods and discharging during high-consumption periods

## Hardware Requirements

- Raspberry Pi (with GPIO pins)
- JKBMS compatible battery system
- Soyo inverter
- Shelly power meters
- Fritz!Box for power monitoring (optional)

## Installation

### Prerequisites

- Python 3.12
- Docker and Docker Compose (optional)

### Environment Variables

Create a `.env` file in the project root with the following variables:

```
SHELLY_URL=http://your-shelly-device-ip/rpc
SHELLY_USER=your-shelly-username
SHELLY_PASSWORD=your-shelly-password
FRITZ_URL=http://your-fritzbox-ip
```

### Setup

1. Clone this repository:
   ```
   git clone https://github.com/yourusername/battery.git
   cd battery
   ```

2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Run the application:
   ```
   python main.py
   ```

### Using Docker

Alternatively, you can run the application using Docker Compose:

```
docker-compose up -d
```

## Features

- **Smart Power Management**: Automatically charges during low consumption periods and discharges during high consumption
- **Battery Protection**: Monitors cell voltages to prevent over-charging or over-discharging
- **Daily Cycle Management**: Ensures the battery is fully charged once per day
- **Real-time Monitoring**: Provides real-time status information via JSON output

## Calibration

The system includes calibration tools to optimize the power settings:

1. Run the calibration script:
   ```
   python calibrate.py
   ```

2. The script will test different power settings and save the results to `calibration.json`

## Monitoring

The system writes its status to `/www/battery.json` with the following information:
- Current state (CHARGE, DISCHARGE, IDLE)
- Battery percentage
- Battery power
- Average cell voltage
- Cell voltage drift
- Last error (if any)
- Last update timestamp

## License

[Your License Here]

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request. 