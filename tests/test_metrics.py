"""Test metrics formatting and output functionality."""

import socket
import tempfile
from unittest import mock
from unittest.mock import MagicMock, patch

import pytest

from systemd_unit_monitor import SystemdUnitMonitor, UnitStats


class TestMetricsFormatting:
    """Test metrics formatting and Telegraf output."""

    @pytest.fixture
    def monitor(self):
        """Create a monitor instance with mocked D-Bus."""
        with mock.patch("dbus.mainloop.glib.DBusGMainLoop"), mock.patch("dbus.SessionBus"):
            monitor = SystemdUnitMonitor()
            monitor.username = "testuser"
            monitor.uid = 1000
            return monitor

    @pytest.fixture
    def sample_stats(self):
        """Create sample unit statistics."""
        return UnitStats(
            name="nginx.service",
            active_state="active",
            sub_state="running", 
            load_state="loaded",
            unit_file_state="enabled",
            main_pid=1234,
            restart_count=0,
            memory_current=52428800,  # 50MB
            cpu_usage_nsec=1234567890,
            timestamp=1639123456.789
        )

    def test_influxdb_line_protocol_format(self, monitor, sample_stats):
        """Test correct InfluxDB line protocol formatting."""
        # Mock socket to capture output
        mock_socket = MagicMock()
        
        with patch("socket.socket", return_value=mock_socket):
            monitor.send_to_telegraf(sample_stats)
        
        # Verify socket.send was called
        mock_socket.send.assert_called_once()
        sent_data = mock_socket.send.call_args[0][0].decode("utf-8")
        
        # Parse the line protocol
        parts = sent_data.strip().split(" ")
        assert len(parts) == 3  # measurement,tags fields timestamp
        
        measurement_and_tags, fields, timestamp = parts
        
        # Check measurement
        assert measurement_and_tags.startswith("systemd_units,")
        
        # Check tags
        tags_part = measurement_and_tags[len("systemd_units,"):]
        expected_tags = {
            'unit': '"nginx.service"',
            'active_state': '"active"',
            'sub_state': '"running"',
            'load_state': '"loaded"',
            'unit_file_state': '"enabled"',
            'username': '"testuser"',
            'uid': '"1000"'
        }
        
        for tag in tags_part.split(","):
            key, value = tag.split("=", 1)
            assert key in expected_tags
            assert expected_tags[key] == value
        
        # Check fields
        expected_fields = [
            "main_pid=1234i",
            "restart_count=0i", 
            "memory_current=52428800i",
            "cpu_usage_nsec=1234567890i"
        ]
        
        for field in expected_fields:
            assert field in fields
        
        # Check timestamp (nanoseconds)
        expected_timestamp = int(1639123456.789 * 1_000_000_000)
        assert timestamp == str(expected_timestamp)

    def test_custom_measurement_name(self, monitor, sample_stats):
        """Test custom measurement name from config."""
        monitor.config.set("telegraf", "measurement", "custom_units")
        
        mock_socket = MagicMock()
        with patch("socket.socket", return_value=mock_socket):
            monitor.send_to_telegraf(sample_stats)
        
        sent_data = mock_socket.send.call_args[0][0].decode("utf-8")
        assert sent_data.startswith("custom_units,")

    def test_socket_connection_error(self, monitor, sample_stats, caplog):
        """Test handling of socket connection errors."""
        mock_socket = MagicMock()
        mock_socket.connect.side_effect = ConnectionRefusedError("Connection refused")
        
        with patch("socket.socket", return_value=mock_socket):
            # Should not raise exception
            monitor.send_to_telegraf(sample_stats)
        
        # Should log warning
        assert "Failed to send to Telegraf socket" in caplog.text

    def test_socket_send_error(self, monitor, sample_stats, caplog):
        """Test handling of socket send errors.""" 
        mock_socket = MagicMock()
        mock_socket.send.side_effect = BrokenPipeError("Broken pipe")
        
        with patch("socket.socket", return_value=mock_socket):
            monitor.send_to_telegraf(sample_stats)
        
        assert "Failed to send to Telegraf socket" in caplog.text

    def test_socket_cleanup_on_error(self, monitor, sample_stats):
        """Test that socket is properly closed even on errors."""
        mock_socket = MagicMock()
        mock_socket.connect.side_effect = ConnectionRefusedError("Connection refused")
        
        with patch("socket.socket", return_value=mock_socket):
            monitor.send_to_telegraf(sample_stats)
        
        # Socket should still be closed
        mock_socket.close.assert_called_once()

    def test_socket_cleanup_on_success(self, monitor, sample_stats):
        """Test that socket is properly closed on successful send."""
        mock_socket = MagicMock()
        
        with patch("socket.socket", return_value=mock_socket):
            monitor.send_to_telegraf(sample_stats)
        
        mock_socket.close.assert_called_once()

    def test_special_characters_in_unit_name(self, monitor):
        """Test handling of special characters in unit names."""
        stats = UnitStats(
            name="my-app@instance.service",
            active_state="active",
            sub_state="running",
            load_state="loaded", 
            unit_file_state="enabled",
            main_pid=1234,
            restart_count=0,
            memory_current=1024,
            cpu_usage_nsec=1000,
            timestamp=1639123456.0
        )
        
        mock_socket = MagicMock()
        with patch("socket.socket", return_value=mock_socket):
            monitor.send_to_telegraf(stats)
        
        sent_data = mock_socket.send.call_args[0][0].decode("utf-8")
        assert 'unit="my-app@instance.service"' in sent_data

    def test_zero_values(self, monitor):
        """Test handling of zero/empty values."""
        stats = UnitStats(
            name="inactive.service",
            active_state="inactive",
            sub_state="dead",
            load_state="loaded",
            unit_file_state="disabled",
            main_pid=0,  # No PID
            restart_count=0,
            memory_current=0,  # No memory usage
            cpu_usage_nsec=0,  # No CPU usage
            timestamp=1639123456.0
        )
        
        mock_socket = MagicMock()
        with patch("socket.socket", return_value=mock_socket):
            monitor.send_to_telegraf(stats)
        
        sent_data = mock_socket.send.call_args[0][0].decode("utf-8")
        
        # Should still include zero values
        assert "main_pid=0i" in sent_data
        assert "memory_current=0i" in sent_data
        assert "cpu_usage_nsec=0i" in sent_data

    def test_large_values(self, monitor):
        """Test handling of large metric values."""
        stats = UnitStats(
            name="memory-hog.service",
            active_state="active",
            sub_state="running",
            load_state="loaded",
            unit_file_state="enabled", 
            main_pid=99999,
            restart_count=1000,
            memory_current=17179869184,  # 16GB
            cpu_usage_nsec=9223372036854775807,  # Max int64
            timestamp=1639123456.0
        )
        
        mock_socket = MagicMock()
        with patch("socket.socket", return_value=mock_socket):
            monitor.send_to_telegraf(stats)
        
        sent_data = mock_socket.send.call_args[0][0].decode("utf-8")
        
        assert "main_pid=99999i" in sent_data
        assert "restart_count=1000i" in sent_data
        assert "memory_current=17179869184i" in sent_data
        assert "cpu_usage_nsec=9223372036854775807i" in sent_data

    def test_custom_telegraf_socket_path(self, monitor, sample_stats):
        """Test custom Telegraf socket path configuration."""
        custom_path = "/tmp/custom-telegraf.sock"
        monitor.telegraf_socket_path = custom_path
        
        mock_socket = MagicMock()
        with patch("socket.socket", return_value=mock_socket):
            monitor.send_to_telegraf(sample_stats)
        
        mock_socket.connect.assert_called_once_with(custom_path)

    def test_utf8_encoding(self, monitor, sample_stats):
        """Test that data is properly UTF-8 encoded."""
        mock_socket = MagicMock()
        
        with patch("socket.socket", return_value=mock_socket):
            monitor.send_to_telegraf(sample_stats)
        
        sent_data = mock_socket.send.call_args[0][0]
        
        # Should be bytes
        assert isinstance(sent_data, bytes)
        
        # Should be valid UTF-8
        decoded = sent_data.decode("utf-8")
        assert isinstance(decoded, str)
        assert decoded.endswith("\n")  # Should end with newline

    def test_debug_logging(self, monitor, sample_stats, caplog):
        """Test debug logging of successful sends."""
        import logging
        caplog.set_level(logging.DEBUG)
        
        mock_socket = MagicMock()
        with patch("socket.socket", return_value=mock_socket):
            monitor.send_to_telegraf(sample_stats)
        
        assert "Sent stats for nginx.service" in caplog.text