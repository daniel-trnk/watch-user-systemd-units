# SystemD Unit Monitor

A Python application that monitors systemd user units via D-Bus and sends comprehensive metrics to Telegraf in InfluxDB line protocol format.

## Quick Start

```bash
# Install system dependencies first (see "System Requirements" below)
# then:
#
# Create a virtual environment + install dependencies (recommended)
uv sync --extra dev --extra tests

# Run
uv run systemd-unit-monitor -c config.ini
```

## Features

- **Real-time monitoring** of systemd user units via D-Bus
- **Event-driven updates** for unit state changes (start/stop/restart/failure)
- **Comprehensive metrics** including:
  - Unit states (active, sub, load, file states)
  - Resource usage (memory, CPU)
  - Process information (PID, restart count)
- **Configurable filtering** with include/exclude patterns supporting wildcards
- **InfluxDB line protocol** output to Telegraf Unix socket
- **Periodic polling** with configurable intervals
- **Robust error handling** and logging

## Installation

### From Source

```bash
# Install in development mode
uv pip install -e .
```

### Build Wheel

```bash
# Build distributable wheel
uv build --wheel

# Install from wheel
pip install dist/systemd_unit_monitor-*.whl
```

### Install from a Release Wheel

If you have a wheel from CI/releases, install it with:

```bash
pip install systemd_unit_monitor-*-py3-none-*.whl
systemd-unit-monitor --help
```

## Usage

### Command Line

```bash
# Run with default settings
systemd-unit-monitor

# Run with custom config
systemd-unit-monitor -c /path/to/config.ini

# Enable verbose logging
systemd-unit-monitor -v -c config.ini
```

### As Python Module

```bash
# Run via uv
uv run systemd-unit-monitor -c config.ini

# Run as module
python -m systemd_unit_monitor
```

## Configuration

The application uses an INI-style configuration file. See `config.ini` for a complete example:

```ini
[logging]
# Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL
level = INFO
format = %(asctime)s - %(name)s - %(levelname)s - %(message)s

[telegraf]
# Path to Telegraf socket (default: /run/telegraf/telegraf.sock)
socket_path = /run/telegraf/telegraf.sock
# InfluxDB measurement name
measurement = systemd_units

[filters]
# Include patterns (comma-separated, empty means include all)
# Examples: *.service, nginx.*, *backup*
include = 

# Exclude patterns (comma-separated)
# Examples: *.mount, *.swap, tmp-*
exclude = *.mount,*.swap,tmp-*,proc-*

[monitoring]
# How often to poll units for status updates (seconds)
poll_interval = 10
```

### Filter Patterns

- **Include patterns**: If specified, only units matching these patterns will be monitored
- **Exclude patterns**: Units matching these patterns will be excluded from monitoring
- **Wildcards**: Use `*` for glob-style pattern matching (e.g., `*.service`, `nginx-*`)
- **Multiple patterns**: Separate with commas

## Metrics Output

The application sends metrics in InfluxDB line protocol format to a Telegraf Unix socket:

```
systemd_units,unit="nginx.service",active_state="active",sub_state="running",load_state="loaded",unit_file_state="enabled",username="user",uid="1000" main_pid=1234i,restart_count=0i,memory_current=52428800i,cpu_usage_nsec=1234567890i 1639123456789000000
```

### Tags
- `unit`: Unit name
- `active_state`: Current active state (active, inactive, failed, etc.)
- `sub_state`: Current sub state (running, exited, dead, etc.)
- `load_state`: Load state (loaded, not-found, etc.)
- `unit_file_state`: Unit file state (enabled, disabled, static, etc.)
- `username`: Username running the systemd user session
- `uid`: User ID running the systemd user session

### Fields
- `main_pid`: Main process ID (for services)
- `restart_count`: Number of service restarts
- `memory_current`: Current memory usage in bytes
- `cpu_usage_nsec`: CPU usage in nanoseconds

## System Requirements

- **Python 3.13+**
- **D-Bus** system with systemd user session
- **System packages**:
  - `dbus-1-dev` (for dbus-python compilation)
  - `libgirepository1.0-dev` (for PyGObject)
  - `python3-gi-dev` (GObject introspection)

### Installing System Dependencies

**Ubuntu/Debian:**
```bash
sudo apt install dbus libdbus-1-dev libgirepository1.0-dev python3-gi-dev
```

**Fedora/RHEL:**
```bash
sudo dnf install dbus-devel gobject-introspection-devel python3-gobject-devel
```

## Development

### Setup Development Environment

```bash
# Install with development dependencies
uv sync --extra dev --extra tests

# Run linting and formatting
uv run ruff check .
uv run ruff format .

# Type checking
uv run pyright systemd_unit_monitor.py
```

### Running Tests

```bash
uv run pytest

# With coverage (matches CI)
uv run pytest tests/ --cov=systemd_unit_monitor --cov-report=term-missing
```

## Troubleshooting

### Common Issues

1. **D-Bus connection errors**: Ensure systemd user session is running
2. **Permission errors**: Check Telegraf socket permissions
3. **Import errors**: Verify system packages are installed
4. **No units found**: Check filter patterns in configuration

### Debugging

Enable verbose logging to troubleshoot issues:

```bash
systemd-unit-monitor -v -c config.ini
```

## License

MIT License. See `LICENSE.txt`.