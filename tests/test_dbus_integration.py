"""Test D-Bus integration and monitoring functionality."""

from unittest import mock
from unittest.mock import MagicMock, patch

import pytest

from systemd_unit_monitor import SystemdUnitMonitor, UnitStats


class TestDBusIntegration:
    """Test D-Bus integration with mocked systemd."""

    @pytest.fixture
    def mock_dbus_setup(self):
        """Set up mocked D-Bus components."""
        with patch("dbus.mainloop.glib.DBusGMainLoop") as mock_mainloop:
            with patch("dbus.SessionBus") as mock_session_bus:
                mock_bus = MagicMock()
                mock_session_bus.return_value = mock_bus
                
                mock_systemd_obj = MagicMock()
                mock_bus.get_object.return_value = mock_systemd_obj
                
                mock_manager = MagicMock()
                
                with patch("dbus.Interface", return_value=mock_manager):
                    yield {
                        "bus": mock_bus,
                        "systemd_obj": mock_systemd_obj,
                        "manager": mock_manager,
                        "mainloop": mock_mainloop
                    }

    def test_systemd_connection(self, mock_dbus_setup):
        """Test successful connection to systemd D-Bus service."""
        monitor = SystemdUnitMonitor()
        monitor.connect_to_systemd()
        
        # Verify D-Bus setup
        mock_dbus_setup["bus"].get_object.assert_called_with(
            "org.freedesktop.systemd1", "/org/freedesktop/systemd1"
        )
        
        # Verify manager subscription
        mock_dbus_setup["manager"].Subscribe.assert_called_once()
        
        # Verify signal receivers are added
        assert mock_dbus_setup["bus"].add_signal_receiver.call_count == 3

    def test_systemd_connection_failure(self, mock_dbus_setup):
        """Test handling of systemd connection failure."""
        mock_dbus_setup["bus"].get_object.side_effect = Exception("D-Bus connection failed")
        
        monitor = SystemdUnitMonitor()
        
        with pytest.raises(SystemExit):
            monitor.connect_to_systemd()

    def test_get_all_units(self, mock_dbus_setup):
        """Test retrieving unit list from systemd."""
        # Mock unit list response
        mock_units = [
            ("nginx.service", "Unit description", "loaded", "active", "running", "", 
             "/org/freedesktop/systemd1/unit/nginx_2eservice", 0, "", ""),
            ("user.mount", "User mount", "loaded", "active", "mounted", "",
             "/org/freedesktop/systemd1/unit/user_2emount", 0, "", ""),
            ("backup.timer", "Backup timer", "loaded", "active", "waiting", "",
             "/org/freedesktop/systemd1/unit/backup_2etimer", 0, "", ""),
        ]
        mock_dbus_setup["manager"].ListUnits.return_value = mock_units
        
        monitor = SystemdUnitMonitor()
        monitor.connect_to_systemd()
        
        # Test with no filters
        units = monitor.get_all_units()
        
        assert len(units) == 3
        assert "nginx.service" in units
        assert "user.mount" in units  
        assert "backup.timer" in units

    def test_get_all_units_with_filters(self, mock_dbus_setup):
        """Test unit filtering during retrieval."""
        mock_units = [
            ("nginx.service", "", "loaded", "active", "running", "", "", 0, "", ""),
            ("user.mount", "", "loaded", "active", "mounted", "", "", 0, "", ""),
            ("backup.timer", "", "loaded", "active", "waiting", "", "", 0, "", ""),
        ]
        mock_dbus_setup["manager"].ListUnits.return_value = mock_units
        
        monitor = SystemdUnitMonitor()
        monitor.include_patterns = ["*.service", "*.timer"]
        monitor.exclude_patterns = ["backup.*"]
        monitor.connect_to_systemd()
        
        units = monitor.get_all_units()
        
        assert len(units) == 1
        assert "nginx.service" in units
        assert "user.mount" not in units  # Not in include
        assert "backup.timer" not in units  # In exclude

    def test_get_all_units_failure(self, mock_dbus_setup):
        """Test handling of ListUnits failure."""
        mock_dbus_setup["manager"].ListUnits.side_effect = Exception("ListUnits failed")
        
        monitor = SystemdUnitMonitor()
        monitor.connect_to_systemd()
        
        units = monitor.get_all_units()
        assert units == []

    def test_get_unit_stats_service(self, mock_dbus_setup):
        """Test getting statistics for a service unit."""
        # Mock GetUnit response
        unit_path = "/org/freedesktop/systemd1/unit/nginx_2eservice"
        mock_dbus_setup["manager"].GetUnit.return_value = unit_path
        
        # Mock unit object and properties
        mock_unit_obj = MagicMock()
        mock_dbus_setup["bus"].get_object.side_effect = [
            mock_dbus_setup["systemd_obj"],  # First call for systemd object
            mock_unit_obj  # Second call for unit object
        ]
        
        mock_props = MagicMock()
        
        # Mock property values
        def get_property(interface, prop):
            props = {
                ("org.freedesktop.systemd1.Unit", "ActiveState"): "active",
                ("org.freedesktop.systemd1.Unit", "SubState"): "running", 
                ("org.freedesktop.systemd1.Unit", "LoadState"): "loaded",
                ("org.freedesktop.systemd1.Unit", "UnitFileState"): "enabled",
                ("org.freedesktop.systemd1.Unit", "MemoryCurrent"): 52428800,
                ("org.freedesktop.systemd1.Unit", "CPUUsageNSec"): 1234567890,
                ("org.freedesktop.systemd1.Service", "MainPID"): 1234,
                ("org.freedesktop.systemd1.Service", "NRestarts"): 2,
            }
            return props.get((interface, prop), "unknown")
        
        mock_props.Get.side_effect = get_property
        
        with patch("dbus.Interface", return_value=mock_props):
            monitor = SystemdUnitMonitor() 
            monitor.connect_to_systemd()
            
            stats = monitor.get_unit_stats("nginx.service")
        
        assert stats is not None
        assert stats.name == "nginx.service"
        assert stats.active_state == "active"
        assert stats.sub_state == "running"
        assert stats.load_state == "loaded" 
        assert stats.unit_file_state == "enabled"
        assert stats.main_pid == 1234
        assert stats.restart_count == 2
        assert stats.memory_current == 52428800
        assert stats.cpu_usage_nsec == 1234567890

    def test_get_unit_stats_non_service(self, mock_dbus_setup):
        """Test getting statistics for a non-service unit."""
        unit_path = "/org/freedesktop/systemd1/unit/user_2emount"
        mock_dbus_setup["manager"].GetUnit.return_value = unit_path
        
        mock_unit_obj = MagicMock()
        mock_dbus_setup["bus"].get_object.side_effect = [
            mock_dbus_setup["systemd_obj"],
            mock_unit_obj
        ]
        
        mock_props = MagicMock()
        mock_props.Get.side_effect = lambda iface, prop: {
            ("org.freedesktop.systemd1.Unit", "ActiveState"): "active",
            ("org.freedesktop.systemd1.Unit", "SubState"): "mounted",
            ("org.freedesktop.systemd1.Unit", "LoadState"): "loaded",
        }.get((iface, prop), "unknown")
        
        with patch("dbus.Interface", return_value=mock_props):
            monitor = SystemdUnitMonitor()
            monitor.connect_to_systemd()
            
            stats = monitor.get_unit_stats("user.mount")
        
        assert stats is not None
        assert stats.name == "user.mount"
        assert stats.main_pid == 0  # No PID for mounts
        assert stats.restart_count == 0  # No restarts for mounts

    def test_get_unit_stats_failure(self, mock_dbus_setup):
        """Test handling of GetUnit failure.""" 
        mock_dbus_setup["manager"].GetUnit.side_effect = Exception("Unit not found")
        
        monitor = SystemdUnitMonitor()
        monitor.connect_to_systemd()
        
        stats = monitor.get_unit_stats("nonexistent.service")
        assert stats is None

    def test_unit_new_signal(self, mock_dbus_setup):
        """Test handling of UnitNew D-Bus signal."""
        monitor = SystemdUnitMonitor()
        monitor.connect_to_systemd()
        
        # Mock get_unit_stats for the new unit
        with patch.object(monitor, "get_unit_stats") as mock_get_stats:
            with patch.object(monitor, "send_to_telegraf") as mock_send:
                mock_stats = UnitStats(
                    name="new.service", active_state="active", sub_state="running",
                    load_state="loaded", unit_file_state="enabled", main_pid=5678,
                    restart_count=0, memory_current=1024, cpu_usage_nsec=1000,
                    timestamp=1639123456.0
                )
                mock_get_stats.return_value = mock_stats
                
                # Simulate signal
                monitor.on_unit_new("new.service", "/path/to/unit")
                
                assert "new.service" in monitor.filtered_units
                mock_get_stats.assert_called_once_with("new.service")
                mock_send.assert_called_once_with(mock_stats)

    def test_unit_removed_signal(self, mock_dbus_setup):
        """Test handling of UnitRemoved D-Bus signal."""
        monitor = SystemdUnitMonitor()
        monitor.connect_to_systemd()
        
        # Add unit to tracked units
        monitor.filtered_units.add("old.service")
        monitor.units["old.service"] = UnitStats(
            name="old.service", active_state="inactive", sub_state="dead",
            load_state="loaded", unit_file_state="enabled", main_pid=0,
            restart_count=0, memory_current=0, cpu_usage_nsec=0,
            timestamp=1639123456.0
        )
        
        # Simulate signal
        monitor.on_unit_removed("old.service", "/path/to/unit")
        
        assert "old.service" not in monitor.filtered_units
        assert "old.service" not in monitor.units

    def test_properties_changed_signal(self, mock_dbus_setup):
        """Test handling of PropertiesChanged D-Bus signal."""
        monitor = SystemdUnitMonitor()
        monitor.connect_to_systemd()
        
        # This should not raise any exceptions
        monitor.on_properties_changed(
            "org.freedesktop.systemd1.Unit",
            {"ActiveState": "active"},
            []
        )

    def test_collect_and_send_unit_stats_state_change(self, mock_dbus_setup):
        """Test state change detection and logging."""
        monitor = SystemdUnitMonitor()
        
        # Create old stats
        old_stats = UnitStats(
            name="test.service", active_state="inactive", sub_state="dead",
            load_state="loaded", unit_file_state="enabled", main_pid=0,
            restart_count=0, memory_current=0, cpu_usage_nsec=0,
            timestamp=1639123456.0
        )
        monitor.units["test.service"] = old_stats
        
        # Create new stats with different state
        new_stats = UnitStats(
            name="test.service", active_state="active", sub_state="running",
            load_state="loaded", unit_file_state="enabled", main_pid=1234,
            restart_count=1, memory_current=1024, cpu_usage_nsec=1000,
            timestamp=1639123457.0
        )
        
        with patch.object(monitor, "get_unit_stats", return_value=new_stats):
            with patch.object(monitor, "send_to_telegraf") as mock_send:
                with patch.object(monitor.logger, "info") as mock_log:
                    monitor.collect_and_send_unit_stats("test.service")
                    
                    # Should update stored stats
                    assert monitor.units["test.service"] == new_stats
                    
                    # Should send to telegraf
                    mock_send.assert_called_once_with(new_stats)
                    
                    # Should log state change
                    mock_log.assert_called_with(
                        "Unit test.service state changed: inactive -> active"
                    )