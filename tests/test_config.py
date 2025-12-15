"""Test configuration loading functionality."""

import configparser
import os
import tempfile
from unittest import mock

import pytest

from systemd_unit_monitor import SystemdUnitMonitor


class TestConfigLoading:
    """Test configuration loading and default values."""

    def test_default_config_values(self):
        """Test that default configuration values are set correctly."""
        with mock.patch("dbus.mainloop.glib.DBusGMainLoop"), mock.patch("dbus.SessionBus"):
            monitor = SystemdUnitMonitor()
            
            config = monitor.config
            
            # Test default values
            assert config.get("logging", "level") == "INFO"
            assert config.get("telegraf", "socket_path") == "/run/telegraf/telegraf.sock"
            assert config.get("telegraf", "measurement") == "systemd_units"
            assert config.get("monitoring", "poll_interval") == "10"
            assert config.get("filters", "include") == ""
            assert config.get("filters", "exclude") == ""

    def test_config_file_override(self):
        """Test that config file values override defaults."""
        config_content = """
[logging]
level = DEBUG
format = custom format

[telegraf]
socket_path = /custom/socket
measurement = custom_units

[filters]
include = *.service
exclude = *.mount,*.swap

[monitoring]
poll_interval = 30
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ini", delete=False) as f:
            f.write(config_content)
            config_file = f.name

        try:
            with mock.patch("dbus.mainloop.glib.DBusGMainLoop"), mock.patch("dbus.SessionBus"):
                monitor = SystemdUnitMonitor(config_file=config_file)
                
                config = monitor.config
                
                # Test overridden values
                assert config.get("logging", "level") == "DEBUG"
                assert config.get("logging", "format") == "custom format"
                assert config.get("telegraf", "socket_path") == "/custom/socket"
                assert config.get("telegraf", "measurement") == "custom_units"
                assert config.get("filters", "include") == "*.service"
                assert config.get("filters", "exclude") == "*.mount,*.swap"
                assert config.get("monitoring", "poll_interval") == "30"
        finally:
            os.unlink(config_file)

    def test_nonexistent_config_file(self):
        """Test behavior when config file doesn't exist."""
        with mock.patch("dbus.mainloop.glib.DBusGMainLoop"), mock.patch("dbus.SessionBus"):
            monitor = SystemdUnitMonitor(config_file="/nonexistent/config.ini")
            
            # Should still have default values
            assert monitor.config.get("logging", "level") == "INFO"

    def test_filter_list_parsing(self):
        """Test filter list parsing from config strings."""
        with mock.patch("dbus.mainloop.glib.DBusGMainLoop"), mock.patch("dbus.SessionBus"):
            monitor = SystemdUnitMonitor()
            
            # Test empty string
            assert monitor._parse_filter_list("") == []
            assert monitor._parse_filter_list("   ") == []
            
            # Test single pattern
            assert monitor._parse_filter_list("*.service") == ["*.service"]
            
            # Test multiple patterns
            assert monitor._parse_filter_list("*.service,*.timer") == ["*.service", "*.timer"]
            
            # Test with spaces
            assert monitor._parse_filter_list(" *.service , *.timer , *.target ") == [
                "*.service", "*.timer", "*.target"
            ]
            
            # Test with empty elements
            assert monitor._parse_filter_list("*.service,,*.timer") == ["*.service", "*.timer"]

    def test_user_info_capture(self):
        """Test that username and UID are captured correctly."""
        with mock.patch("dbus.mainloop.glib.DBusGMainLoop"), mock.patch("dbus.SessionBus"):
            with mock.patch("getpass.getuser", return_value="testuser"):
                with mock.patch("os.getuid", return_value=1000):
                    monitor = SystemdUnitMonitor()
                    
                    assert monitor.username == "testuser"
                    assert monitor.uid == 1000