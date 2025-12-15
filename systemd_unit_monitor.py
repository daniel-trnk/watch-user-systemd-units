#!/usr/bin/env python3
"""SystemD User Unit Monitor.

Monitors systemd user units via D-Bus and sends metrics to Telegraf.

License: MIT
Copyright: 2025 Terank Technologies AG

Usage:
    systemd-unit-monitor [-c CONFIG] [-v]

Options:
    -c CONFIG, --config CONFIG  Configuration file path
    -v, --verbose               Enable verbose logging

Example:
    systemd-unit-monitor -c config.ini -v
    
"""

import argparse
import configparser
import contextlib
import getpass
import logging
import os
import socket
import sys
import time
from dataclasses import dataclass

import dbus
import dbus.mainloop.glib
from gi.repository import GLib


@dataclass
class UnitStats:
    """Statistics for a systemd unit."""

    name: str
    active_state: str
    sub_state: str
    load_state: str
    unit_file_state: str
    main_pid: int
    restart_count: int
    memory_current: int
    cpu_usage_nsec: int
    timestamp: float


class SystemdUnitMonitor:
    """Monitor systemd user units and send metrics to Telegraf."""

    def __init__(self, config_file: str | None = None) -> None:
        self.config = self._load_config(config_file)
        self.setup_logging()

        # D-Bus setup
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.session_bus = dbus.SessionBus()
        self.systemd = None

        # State tracking
        self.units: dict[str, UnitStats] = {}
        self.filtered_units: set[str] = set()

        # Telegraf socket
        self.telegraf_socket_path = self.config.get(
            "telegraf", "socket_path", fallback="/run/telegraf/telegraf.sock"
        )

        # Filters
        self.include_patterns = self._parse_filter_list(
            self.config.get("filters", "include", fallback="")
        )
        self.exclude_patterns = self._parse_filter_list(
            self.config.get("filters", "exclude", fallback="")
        )
        
        # User information
        self.username = getpass.getuser()
        self.uid = os.getuid()

    def _load_config(self, config_file: str | None) -> configparser.ConfigParser:
        """Load configuration from file."""
        config = configparser.ConfigParser()

        # Set defaults
        config.add_section("logging")
        config.set("logging", "level", "INFO")
        config.set("logging", "format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")

        config.add_section("telegraf")
        config.set("telegraf", "socket_path", "/run/telegraf/telegraf.sock")
        config.set("telegraf", "measurement", "systemd_units")

        config.add_section("filters")
        config.set("filters", "include", "")
        config.set("filters", "exclude", "")

        config.add_section("monitoring")
        config.set("monitoring", "poll_interval", "10")

        if config_file and os.path.exists(config_file):
            config.read(config_file)

        return config

    def setup_logging(self) -> None:
        """Set up logging configuration."""
        level = getattr(logging, self.config.get("logging", "level", fallback="INFO").upper())
        format_str = self.config.get(
            "logging",
            "format",
            fallback="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )

        logging.basicConfig(level=level, format=format_str)
        self.logger = logging.getLogger(__name__)

    def _parse_filter_list(self, filter_str: str) -> list[str]:
        """Parse comma-separated filter patterns."""
        if not filter_str.strip():
            return []
        return [pattern.strip() for pattern in filter_str.split(",") if pattern.strip()]

    def _should_monitor_unit(self, unit_name: str) -> bool:
        """Check if unit should be monitored based on filters."""
        import fnmatch

        # If include patterns are specified, unit must match at least one
        if self.include_patterns and not any(
            fnmatch.fnmatch(unit_name, pattern) for pattern in self.include_patterns
        ):
            return False

        # If exclude patterns are specified, unit must not match any
        return not (
            self.exclude_patterns
            and any(fnmatch.fnmatch(unit_name, pattern) for pattern in self.exclude_patterns)
        )

    def connect_to_systemd(self) -> None:
        """Connect to systemd user manager via D-Bus."""
        try:
            self.systemd = self.session_bus.get_object(
                "org.freedesktop.systemd1", "/org/freedesktop/systemd1"
            )
            self.manager = dbus.Interface(self.systemd, "org.freedesktop.systemd1.Manager")
            self.logger.info("Connected to systemd user manager")

            # Subscribe to unit changes
            self.manager.Subscribe()

            # Connect to signals
            self.session_bus.add_signal_receiver(
                self.on_unit_new,
                signal_name="UnitNew",
                dbus_interface="org.freedesktop.systemd1.Manager",
            )

            self.session_bus.add_signal_receiver(
                self.on_unit_removed,
                signal_name="UnitRemoved",
                dbus_interface="org.freedesktop.systemd1.Manager",
            )

            self.session_bus.add_signal_receiver(
                self.on_properties_changed,
                signal_name="PropertiesChanged",
                dbus_interface="org.freedesktop.DBus.Properties",
            )

        except Exception as e:
            self.logger.error(f"Failed to connect to systemd: {e}")
            sys.exit(1)

    def get_all_units(self) -> list[str]:
        """Get list of all systemd units."""
        try:
            units = self.manager.ListUnits()
            unit_names = []

            for unit_info in units:
                unit_name = unit_info[0]
                if self._should_monitor_unit(unit_name):
                    unit_names.append(unit_name)
                    self.filtered_units.add(unit_name)

            self.logger.info(f"Found {len(unit_names)} units to monitor")
            return unit_names

        except Exception as e:
            self.logger.error(f"Failed to get unit list: {e}")
            return []

    def get_unit_stats(self, unit_name: str) -> UnitStats | None:
        """Get statistics for a specific unit."""
        try:
            unit_path = self.manager.GetUnit(unit_name)
            unit_obj = self.session_bus.get_object("org.freedesktop.systemd1", unit_path)
            unit_props = dbus.Interface(unit_obj, "org.freedesktop.DBus.Properties")

            # Get basic properties
            active_state = str(unit_props.Get("org.freedesktop.systemd1.Unit", "ActiveState"))
            sub_state = str(unit_props.Get("org.freedesktop.systemd1.Unit", "SubState"))
            load_state = str(unit_props.Get("org.freedesktop.systemd1.Unit", "LoadState"))

            # Get service-specific properties if it's a service
            main_pid = 0
            restart_count = 0
            memory_current = 0
            cpu_usage_nsec = 0
            unit_file_state = "unknown"

            try:
                if unit_name.endswith(".service"):
                    main_pid = int(unit_props.Get("org.freedesktop.systemd1.Service", "MainPID"))
                    restart_count = int(
                        unit_props.Get("org.freedesktop.systemd1.Service", "NRestarts")
                    )

                # Get resource usage
                with contextlib.suppress(Exception):
                    memory_current = int(
                        unit_props.Get("org.freedesktop.systemd1.Unit", "MemoryCurrent")
                    )

                with contextlib.suppress(Exception):
                    cpu_usage_nsec = int(
                        unit_props.Get("org.freedesktop.systemd1.Unit", "CPUUsageNSec")
                    )

                with contextlib.suppress(Exception):
                    unit_file_state = str(
                        unit_props.Get("org.freedesktop.systemd1.Unit", "UnitFileState")
                    )

            except Exception as e:
                self.logger.debug(f"Could not get extended properties for {unit_name}: {e}")

            return UnitStats(
                name=unit_name,
                active_state=active_state,
                sub_state=sub_state,
                load_state=load_state,
                unit_file_state=unit_file_state,
                main_pid=main_pid,
                restart_count=restart_count,
                memory_current=memory_current,
                cpu_usage_nsec=cpu_usage_nsec,
                timestamp=time.time(),
            )

        except Exception as e:
            self.logger.debug(f"Failed to get stats for {unit_name}: {e}")
            return None

    def send_to_telegraf(self, stats: UnitStats) -> None:
        """Send unit statistics to Telegraf in InfluxDB line protocol format."""
        try:
            measurement = self.config.get("telegraf", "measurement", fallback="systemd_units")

            # Build tags
            tags = [
                f'unit="{stats.name}"',
                f'active_state="{stats.active_state}"',
                f'sub_state="{stats.sub_state}"',
                f'load_state="{stats.load_state}"',
                f'unit_file_state="{stats.unit_file_state}"',
                f'username="{self.username}"',
                f'uid="{self.uid}"',
            ]
            tags_str = ",".join(tags)

            # Build fields
            fields = [
                f"main_pid={stats.main_pid}i",
                f"restart_count={stats.restart_count}i",
                f"memory_current={stats.memory_current}i",
                f"cpu_usage_nsec={stats.cpu_usage_nsec}i",
            ]
            fields_str = ",".join(fields)

            # Create line protocol message
            timestamp_ns = int(stats.timestamp * 1_000_000_000)
            line = f"{measurement},{tags_str} {fields_str} {timestamp_ns}\n"

            # Send to Telegraf socket
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                sock.connect(self.telegraf_socket_path)
                sock.send(line.encode("utf-8"))
                self.logger.debug(f"Sent stats for {stats.name}")
            except Exception as e:
                self.logger.warning(f"Failed to send to Telegraf socket: {e}")
            finally:
                sock.close()

        except Exception as e:
            self.logger.error(f"Error formatting/sending stats for {stats.name}: {e}")

    def on_unit_new(self, unit_name: str, unit_path: str) -> None:
        """Handle new unit signal."""
        unit_name = str(unit_name)
        if self._should_monitor_unit(unit_name):
            self.logger.info(f"New unit detected: {unit_name}")
            self.filtered_units.add(unit_name)
            self.collect_and_send_unit_stats(unit_name)

    def on_unit_removed(self, unit_name: str, unit_path: str) -> None:
        """Handle unit removed signal."""
        unit_name = str(unit_name)
        if unit_name in self.filtered_units:
            self.logger.info(f"Unit removed: {unit_name}")
            self.filtered_units.discard(unit_name)
            self.units.pop(unit_name, None)

    def on_properties_changed(
        self, interface: str, changed_properties: dict, invalidated_properties: list
    ) -> None:
        """Handle unit property changes."""
        if interface == "org.freedesktop.systemd1.Unit":
            # This is called for any unit property change
            # We'll check all monitored units in our polling loop
            pass

    def collect_and_send_unit_stats(self, unit_name: str) -> None:
        """Collect stats for a unit and send to Telegraf."""
        stats = self.get_unit_stats(unit_name)
        if stats:
            old_stats = self.units.get(unit_name)
            self.units[unit_name] = stats

            # Log state changes
            if old_stats and old_stats.active_state != stats.active_state:
                self.logger.info(
                    f"Unit {unit_name} state changed: "
                    f"{old_stats.active_state} -> {stats.active_state}"
                )

            self.send_to_telegraf(stats)

    def poll_units(self) -> None:
        """Poll all monitored units for status updates."""
        for unit_name in list(self.filtered_units):
            self.collect_and_send_unit_stats(unit_name)

    def run(self) -> None:
        """Run the main monitoring loop."""
        self.logger.info("Starting systemd unit monitor")

        # Connect to systemd
        self.connect_to_systemd()

        # Get initial unit list
        initial_units = self.get_all_units()

        # Collect initial stats
        self.logger.info("Collecting initial unit statistics")
        for unit_name in initial_units:
            self.collect_and_send_unit_stats(unit_name)

        # Setup periodic polling
        poll_interval = self.config.getint("monitoring", "poll_interval", fallback=10)
        GLib.timeout_add_seconds(poll_interval, lambda: (self.poll_units(), True)[1])

        # Start GLib main loop
        self.logger.info("Starting monitoring loop")
        try:
            loop = GLib.MainLoop()
            loop.run()
        except KeyboardInterrupt:
            self.logger.info("Shutting down...")
        except Exception as e:
            self.logger.error(f"Monitoring loop error: {e}")


def main() -> None:
    """Run the main application."""
    parser = argparse.ArgumentParser(description="SystemD User Unit Monitor")
    parser.add_argument("-c", "--config", help="Configuration file path")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    # Override log level if verbose
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    monitor = SystemdUnitMonitor(config_file=args.config)
    monitor.run()


if __name__ == "__main__":
    main()
