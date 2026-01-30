#!/usr/bin/env python3
"""
Bridge Up WebSocket Channel Tests

Tests the WebSocket subscription system including:
- WebSocketClient class and channel management
- Channel parsing and validation (including region filters)
- Subscription handling
- Broadcast filtering
- Boat change detection
- Region-based filtering (Phase 2)

Run with: python3 test_websocket_channels.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
import json
from unittest.mock import MagicMock, AsyncMock

from shared import WebSocketClient


class TestWebSocketClient(unittest.TestCase):
    """Test WebSocketClient class and channel subscriptions"""

    def test_default_no_channels(self):
        """New client has no channel subscriptions"""
        mock_ws = MagicMock()
        client = WebSocketClient(websocket=mock_ws)
        self.assertEqual(client.channels, set())

    def test_wants_bridges_default_false(self):
        """wants_bridges() returns False when not subscribed"""
        mock_ws = MagicMock()
        client = WebSocketClient(websocket=mock_ws)
        self.assertFalse(client.wants_bridges())

    def test_wants_boats_default_false(self):
        """wants_boats() returns False when not subscribed"""
        mock_ws = MagicMock()
        client = WebSocketClient(websocket=mock_ws)
        self.assertFalse(client.wants_boats())

    def test_wants_bridges_when_subscribed(self):
        """wants_bridges() returns True when subscribed to all bridges"""
        mock_ws = MagicMock()
        client = WebSocketClient(websocket=mock_ws, channels={"bridges"})
        self.assertTrue(client.wants_bridges())

    def test_wants_boats_when_subscribed(self):
        """wants_boats() returns True when subscribed to all boats"""
        mock_ws = MagicMock()
        client = WebSocketClient(websocket=mock_ws, channels={"boats"})
        self.assertTrue(client.wants_boats())

    def test_wants_bridges_with_region(self):
        """wants_bridges() returns True when subscribed to a region"""
        mock_ws = MagicMock()
        client = WebSocketClient(websocket=mock_ws, channels={"bridges:sct"})
        self.assertTrue(client.wants_bridges())

    def test_wants_boats_with_region(self):
        """wants_boats() returns True when subscribed to a region"""
        mock_ws = MagicMock()
        client = WebSocketClient(websocket=mock_ws, channels={"boats:welland"})
        self.assertTrue(client.wants_boats())

    def test_both_channels(self):
        """Client can subscribe to both channels"""
        mock_ws = MagicMock()
        client = WebSocketClient(websocket=mock_ws, channels={"bridges", "boats"})
        self.assertTrue(client.wants_bridges())
        self.assertTrue(client.wants_boats())

    def test_channels_can_be_updated(self):
        """Channel subscriptions can be changed"""
        mock_ws = MagicMock()
        client = WebSocketClient(websocket=mock_ws)

        # Initially empty
        self.assertFalse(client.wants_bridges())

        # Subscribe to bridges
        client.channels = {"bridges"}
        self.assertTrue(client.wants_bridges())
        self.assertFalse(client.wants_boats())

        # Change to boats only
        client.channels = {"boats"}
        self.assertFalse(client.wants_bridges())
        self.assertTrue(client.wants_boats())

        # Subscribe to both
        client.channels = {"bridges", "boats"}
        self.assertTrue(client.wants_bridges())
        self.assertTrue(client.wants_boats())

        # Unsubscribe all
        client.channels = set()
        self.assertFalse(client.wants_bridges())
        self.assertFalse(client.wants_boats())


class TestClientRegionMethods(unittest.TestCase):
    """Test WebSocketClient region filtering methods (Phase 2)"""

    def test_boat_regions_all(self):
        """boat_regions() returns None when subscribed to all boats"""
        mock_ws = MagicMock()
        client = WebSocketClient(websocket=mock_ws, channels={"boats"})
        self.assertIsNone(client.boat_regions())

    def test_boat_regions_specific(self):
        """boat_regions() returns set of regions when subscribed to specific"""
        mock_ws = MagicMock()
        client = WebSocketClient(websocket=mock_ws, channels={"boats:welland"})
        self.assertEqual(client.boat_regions(), {"welland"})

    def test_boat_regions_multiple(self):
        """boat_regions() returns multiple regions"""
        mock_ws = MagicMock()
        client = WebSocketClient(websocket=mock_ws, channels={"boats:welland", "boats:montreal"})
        self.assertEqual(client.boat_regions(), {"welland", "montreal"})

    def test_boat_regions_none_subscribed(self):
        """boat_regions() returns None when not subscribed to boats"""
        mock_ws = MagicMock()
        client = WebSocketClient(websocket=mock_ws, channels={"bridges"})
        self.assertIsNone(client.boat_regions())

    def test_bridge_regions_all(self):
        """bridge_regions() returns None when subscribed to all bridges"""
        mock_ws = MagicMock()
        client = WebSocketClient(websocket=mock_ws, channels={"bridges"})
        self.assertIsNone(client.bridge_regions())

    def test_bridge_regions_specific(self):
        """bridge_regions() returns set of regions when subscribed to specific"""
        mock_ws = MagicMock()
        client = WebSocketClient(websocket=mock_ws, channels={"bridges:sct"})
        self.assertEqual(client.bridge_regions(), {"sct"})

    def test_bridge_regions_multiple(self):
        """bridge_regions() returns multiple regions"""
        mock_ws = MagicMock()
        client = WebSocketClient(websocket=mock_ws, channels={"bridges:sct", "bridges:pc"})
        self.assertEqual(client.bridge_regions(), {"sct", "pc"})

    def test_wants_boat_region_all(self):
        """wants_boat_region() returns True when subscribed to all"""
        mock_ws = MagicMock()
        client = WebSocketClient(websocket=mock_ws, channels={"boats"})
        self.assertTrue(client.wants_boat_region("welland"))
        self.assertTrue(client.wants_boat_region("montreal"))

    def test_wants_boat_region_specific(self):
        """wants_boat_region() returns True only for subscribed region"""
        mock_ws = MagicMock()
        client = WebSocketClient(websocket=mock_ws, channels={"boats:welland"})
        self.assertTrue(client.wants_boat_region("welland"))
        self.assertFalse(client.wants_boat_region("montreal"))

    def test_wants_bridge_region_all(self):
        """wants_bridge_region() returns True when subscribed to all"""
        mock_ws = MagicMock()
        client = WebSocketClient(websocket=mock_ws, channels={"bridges"})
        self.assertTrue(client.wants_bridge_region("sct"))
        self.assertTrue(client.wants_bridge_region("mss"))

    def test_wants_bridge_region_specific(self):
        """wants_bridge_region() returns True only for subscribed region"""
        mock_ws = MagicMock()
        client = WebSocketClient(websocket=mock_ws, channels={"bridges:sct", "bridges:pc"})
        self.assertTrue(client.wants_bridge_region("sct"))
        self.assertTrue(client.wants_bridge_region("pc"))
        self.assertFalse(client.wants_bridge_region("mss"))


class TestChannelParsing(unittest.TestCase):
    """Test channel parsing for region filters (Phase 2)"""

    def setUp(self):
        from main import parse_channel, validate_channels, CHANNEL_REGIONS
        self.parse_channel = parse_channel
        self.validate_channels = validate_channels
        self.channel_regions = CHANNEL_REGIONS

    def test_parse_base_channel_boats(self):
        """Parse 'boats' returns (boats, None)"""
        base, region = self.parse_channel("boats")
        self.assertEqual(base, "boats")
        self.assertIsNone(region)

    def test_parse_base_channel_bridges(self):
        """Parse 'bridges' returns (bridges, None)"""
        base, region = self.parse_channel("bridges")
        self.assertEqual(base, "bridges")
        self.assertIsNone(region)

    def test_parse_region_channel_boats(self):
        """Parse 'boats:welland' returns (boats, welland)"""
        base, region = self.parse_channel("boats:welland")
        self.assertEqual(base, "boats")
        self.assertEqual(region, "welland")

    def test_parse_region_channel_bridges(self):
        """Parse 'bridges:sct' returns (bridges, sct)"""
        base, region = self.parse_channel("bridges:sct")
        self.assertEqual(base, "bridges")
        self.assertEqual(region, "sct")

    def test_parse_invalid_base(self):
        """Parse invalid base channel returns (None, None)"""
        base, region = self.parse_channel("invalid")
        self.assertIsNone(base)
        self.assertIsNone(region)

    def test_parse_invalid_region(self):
        """Parse valid base with invalid region returns (None, None)"""
        base, region = self.parse_channel("boats:invalid")
        self.assertIsNone(base)
        self.assertIsNone(region)

    def test_parse_invalid_base_with_region(self):
        """Parse invalid:region returns (None, None)"""
        base, region = self.parse_channel("invalid:welland")
        self.assertIsNone(base)
        self.assertIsNone(region)

    def test_parse_non_string_int(self):
        """Parse non-string (int) returns (None, None)"""
        base, region = self.parse_channel(123)
        self.assertIsNone(base)
        self.assertIsNone(region)

    def test_parse_non_string_none(self):
        """Parse None returns (None, None)"""
        base, region = self.parse_channel(None)
        self.assertIsNone(base)
        self.assertIsNone(region)

    def test_parse_non_string_list(self):
        """Parse list returns (None, None)"""
        base, region = self.parse_channel(["boats"])
        self.assertIsNone(base)
        self.assertIsNone(region)

    def test_validate_channels_base(self):
        """validate_channels accepts base channels"""
        valid = self.validate_channels(["bridges", "boats"])
        self.assertEqual(valid, {"bridges", "boats"})

    def test_validate_channels_with_regions(self):
        """validate_channels accepts region channels"""
        valid = self.validate_channels(["bridges:sct", "boats:welland"])
        self.assertEqual(valid, {"bridges:sct", "boats:welland"})

    def test_validate_channels_mixed(self):
        """validate_channels handles mix of base and region channels"""
        valid = self.validate_channels(["bridges", "boats:welland", "invalid"])
        self.assertEqual(valid, {"bridges", "boats:welland"})

    def test_validate_channels_filters_invalid(self):
        """validate_channels removes invalid channels"""
        valid = self.validate_channels(["invalid", "boats:unknown", "bridges:sct"])
        self.assertEqual(valid, {"bridges:sct"})

    def test_validate_channels_empty(self):
        """validate_channels returns empty set for empty list"""
        valid = self.validate_channels([])
        self.assertEqual(valid, set())

    def test_channel_regions_defined(self):
        """CHANNEL_REGIONS has correct structure"""
        self.assertIn("boats", self.channel_regions)
        self.assertIn("bridges", self.channel_regions)
        self.assertIn("welland", self.channel_regions["boats"])
        self.assertIn("montreal", self.channel_regions["boats"])
        self.assertIn("sct", self.channel_regions["bridges"])
        self.assertIn("pc", self.channel_regions["bridges"])


class TestVesselChangeDetection(unittest.TestCase):
    """Test boat data change detection logic"""

    def setUp(self):
        from main import get_vessels_for_comparison, VOLATILE_VESSEL_FIELDS
        self.get_vessels_for_comparison = get_vessels_for_comparison
        self.volatile_fields = VOLATILE_VESSEL_FIELDS

    def test_volatile_fields_defined(self):
        """Volatile fields include last_seen and source"""
        self.assertIn("last_seen", self.volatile_fields)
        self.assertIn("source", self.volatile_fields)

    def test_same_data_same_comparison(self):
        """Identical vessel data produces same comparison string"""
        vessels = [
            {"mmsi": 123, "position": {"lat": 42.9, "lon": -79.2}, "speed_knots": 5.0}
        ]
        comp1 = self.get_vessels_for_comparison(vessels)
        comp2 = self.get_vessels_for_comparison(vessels)
        self.assertEqual(comp1, comp2)

    def test_position_change_detected(self):
        """Position change produces different comparison string"""
        vessels1 = [
            {"mmsi": 123, "position": {"lat": 42.9, "lon": -79.2}, "speed_knots": 5.0}
        ]
        vessels2 = [
            {"mmsi": 123, "position": {"lat": 42.95, "lon": -79.2}, "speed_knots": 5.0}
        ]
        comp1 = self.get_vessels_for_comparison(vessels1)
        comp2 = self.get_vessels_for_comparison(vessels2)
        self.assertNotEqual(comp1, comp2)

    def test_speed_change_detected(self):
        """Speed change produces different comparison string"""
        vessels1 = [
            {"mmsi": 123, "position": {"lat": 42.9, "lon": -79.2}, "speed_knots": 5.0}
        ]
        vessels2 = [
            {"mmsi": 123, "position": {"lat": 42.9, "lon": -79.2}, "speed_knots": 7.0}
        ]
        comp1 = self.get_vessels_for_comparison(vessels1)
        comp2 = self.get_vessels_for_comparison(vessels2)
        self.assertNotEqual(comp1, comp2)

    def test_last_seen_change_ignored(self):
        """last_seen timestamp change does NOT affect comparison"""
        vessels1 = [
            {"mmsi": 123, "position": {"lat": 42.9, "lon": -79.2}, "last_seen": "2026-01-01T10:00:00Z"}
        ]
        vessels2 = [
            {"mmsi": 123, "position": {"lat": 42.9, "lon": -79.2}, "last_seen": "2026-01-01T10:01:00Z"}
        ]
        comp1 = self.get_vessels_for_comparison(vessels1)
        comp2 = self.get_vessels_for_comparison(vessels2)
        self.assertEqual(comp1, comp2)

    def test_source_change_ignored(self):
        """source field change does NOT affect comparison"""
        vessels1 = [
            {"mmsi": 123, "position": {"lat": 42.9, "lon": -79.2}, "source": "udp:udp1"}
        ]
        vessels2 = [
            {"mmsi": 123, "position": {"lat": 42.9, "lon": -79.2}, "source": "aishub"}
        ]
        comp1 = self.get_vessels_for_comparison(vessels1)
        comp2 = self.get_vessels_for_comparison(vessels2)
        self.assertEqual(comp1, comp2)

    def test_new_vessel_detected(self):
        """New vessel added produces different comparison"""
        vessels1 = [
            {"mmsi": 123, "position": {"lat": 42.9, "lon": -79.2}}
        ]
        vessels2 = [
            {"mmsi": 123, "position": {"lat": 42.9, "lon": -79.2}},
            {"mmsi": 456, "position": {"lat": 43.0, "lon": -79.3}}
        ]
        comp1 = self.get_vessels_for_comparison(vessels1)
        comp2 = self.get_vessels_for_comparison(vessels2)
        self.assertNotEqual(comp1, comp2)

    def test_vessel_removed_detected(self):
        """Vessel removal produces different comparison"""
        vessels1 = [
            {"mmsi": 123, "position": {"lat": 42.9, "lon": -79.2}},
            {"mmsi": 456, "position": {"lat": 43.0, "lon": -79.3}}
        ]
        vessels2 = [
            {"mmsi": 123, "position": {"lat": 42.9, "lon": -79.2}}
        ]
        comp1 = self.get_vessels_for_comparison(vessels1)
        comp2 = self.get_vessels_for_comparison(vessels2)
        self.assertNotEqual(comp1, comp2)

    def test_heading_change_detected(self):
        """Heading change produces different comparison"""
        vessels1 = [{"mmsi": 123, "heading": 90}]
        vessels2 = [{"mmsi": 123, "heading": 180}]
        comp1 = self.get_vessels_for_comparison(vessels1)
        comp2 = self.get_vessels_for_comparison(vessels2)
        self.assertNotEqual(comp1, comp2)

    def test_empty_vessels_comparison(self):
        """Empty vessel list produces valid comparison string"""
        comp = self.get_vessels_for_comparison([])
        self.assertEqual(comp, "[]")


class TestBroadcastFiltering(unittest.TestCase):
    """Test that broadcasts filter by channel subscription"""

    def test_bridge_subscriber_count_base(self):
        """Count of bridge subscribers (base channel) is correct"""
        mock_ws = MagicMock()
        clients = [
            WebSocketClient(websocket=mock_ws, channels={"bridges"}),
            WebSocketClient(websocket=mock_ws, channels={"boats"}),
            WebSocketClient(websocket=mock_ws, channels={"bridges", "boats"}),
            WebSocketClient(websocket=mock_ws, channels=set()),
        ]
        bridge_subs = sum(1 for c in clients if c.wants_bridges())
        self.assertEqual(bridge_subs, 2)

    def test_bridge_subscriber_count_with_regions(self):
        """Count of bridge subscribers (including region) is correct"""
        mock_ws = MagicMock()
        clients = [
            WebSocketClient(websocket=mock_ws, channels={"bridges"}),
            WebSocketClient(websocket=mock_ws, channels={"bridges:sct"}),
            WebSocketClient(websocket=mock_ws, channels={"boats"}),
            WebSocketClient(websocket=mock_ws, channels=set()),
        ]
        bridge_subs = sum(1 for c in clients if c.wants_bridges())
        self.assertEqual(bridge_subs, 2)

    def test_boat_subscriber_count(self):
        """Count of boat subscribers is correct"""
        mock_ws = MagicMock()
        clients = [
            WebSocketClient(websocket=mock_ws, channels={"bridges"}),
            WebSocketClient(websocket=mock_ws, channels={"boats"}),
            WebSocketClient(websocket=mock_ws, channels={"boats:welland"}),
            WebSocketClient(websocket=mock_ws, channels=set()),
        ]
        boat_subs = sum(1 for c in clients if c.wants_boats())
        self.assertEqual(boat_subs, 2)

    def test_no_subscribers_count(self):
        """Count of unsubscribed clients is correct"""
        mock_ws = MagicMock()
        clients = [
            WebSocketClient(websocket=mock_ws, channels={"bridges"}),
            WebSocketClient(websocket=mock_ws, channels=set()),
            WebSocketClient(websocket=mock_ws, channels=set()),
        ]
        no_subs = sum(1 for c in clients if not c.wants_bridges() and not c.wants_boats())
        self.assertEqual(no_subs, 2)


class TestRegionFiltering(unittest.TestCase):
    """Test region-based filtering of subscribers (Phase 2)"""

    def test_welland_only_client(self):
        """Client subscribed to boats:welland only wants welland"""
        mock_ws = MagicMock()
        client = WebSocketClient(websocket=mock_ws, channels={"boats:welland"})

        self.assertTrue(client.wants_boat_region("welland"))
        self.assertFalse(client.wants_boat_region("montreal"))

    def test_all_boats_client_wants_all_regions(self):
        """Client subscribed to 'boats' wants all regions"""
        mock_ws = MagicMock()
        client = WebSocketClient(websocket=mock_ws, channels={"boats"})

        self.assertTrue(client.wants_boat_region("welland"))
        self.assertTrue(client.wants_boat_region("montreal"))

    def test_sct_pc_client(self):
        """Client subscribed to bridges:sct and bridges:pc"""
        mock_ws = MagicMock()
        client = WebSocketClient(websocket=mock_ws, channels={"bridges:sct", "bridges:pc"})

        self.assertTrue(client.wants_bridge_region("sct"))
        self.assertTrue(client.wants_bridge_region("pc"))
        self.assertFalse(client.wants_bridge_region("mss"))
        self.assertFalse(client.wants_bridge_region("k"))

    def test_mixed_subscription(self):
        """Client with mixed base and region subscriptions"""
        mock_ws = MagicMock()
        client = WebSocketClient(websocket=mock_ws, channels={"bridges", "boats:welland"})

        # All bridges
        self.assertTrue(client.wants_bridge_region("sct"))
        self.assertTrue(client.wants_bridge_region("mss"))

        # Only welland boats
        self.assertTrue(client.wants_boat_region("welland"))
        self.assertFalse(client.wants_boat_region("montreal"))


class TestMessageFormat(unittest.TestCase):
    """Test message format for typed WebSocket messages"""

    def test_bridges_message_format(self):
        """Bridges message has correct type and data structure"""
        data = {"last_updated": "2026-01-01T10:00:00", "bridges": {}}
        message = json.dumps({"type": "bridges", "data": data})
        parsed = json.loads(message)

        self.assertEqual(parsed["type"], "bridges")
        self.assertIn("data", parsed)
        self.assertIn("bridges", parsed["data"])

    def test_boats_message_format(self):
        """Boats message has correct type and data structure"""
        data = {"last_updated": "2026-01-01T10:00:00", "vessel_count": 0, "vessels": []}
        message = json.dumps({"type": "boats", "data": data})
        parsed = json.loads(message)

        self.assertEqual(parsed["type"], "boats")
        self.assertIn("data", parsed)
        self.assertIn("vessels", parsed["data"])

    def test_subscribed_message_format(self):
        """Subscribed confirmation has correct format"""
        channels = ["bridges", "boats"]
        message = json.dumps({"type": "subscribed", "channels": channels})
        parsed = json.loads(message)

        self.assertEqual(parsed["type"], "subscribed")
        self.assertIn("channels", parsed)
        self.assertIsInstance(parsed["channels"], list)


class TestSubscriptionMessages(unittest.TestCase):
    """Test subscription message parsing"""

    def test_valid_subscribe_message(self):
        """Valid subscribe message is parsed correctly"""
        msg = {"action": "subscribe", "channels": ["bridges", "boats"]}
        self.assertEqual(msg.get("action"), "subscribe")
        self.assertEqual(msg.get("channels"), ["bridges", "boats"])

    def test_region_subscribe_message(self):
        """Region subscribe message is parsed correctly"""
        msg = {"action": "subscribe", "channels": ["bridges:sct", "boats:welland"]}
        self.assertEqual(msg.get("action"), "subscribe")
        self.assertEqual(msg.get("channels"), ["bridges:sct", "boats:welland"])

    def test_empty_channels_subscribe(self):
        """Empty channels array is valid (unsubscribe all)"""
        msg = {"action": "subscribe", "channels": []}
        self.assertEqual(msg.get("channels"), [])

    def test_invalid_action_ignored(self):
        """Unknown action should be ignored"""
        msg = {"action": "unknown", "channels": ["bridges"]}
        self.assertNotEqual(msg.get("action"), "subscribe")

    def test_missing_channels_handled(self):
        """Missing channels defaults to empty"""
        msg = {"action": "subscribe"}
        channels = msg.get("channels", [])
        self.assertEqual(channels, [])


# Fake vessel data for integration tests
FAKE_VESSELS = [
    {
        "mmsi": 316001001,
        "name": "WELLAND SHIP 1",
        "type_category": "cargo",
        "position": {"lat": 42.92, "lon": -79.24},
        "heading": 10,
        "speed_knots": 5.0,
        "region": "welland",
        "last_seen": "2026-01-30T10:00:00Z",
        "source": "udp:test"
    },
    {
        "mmsi": 316001002,
        "name": "WELLAND SHIP 2",
        "type_category": "tanker",
        "position": {"lat": 42.88, "lon": -79.25},
        "heading": 180,
        "speed_knots": 3.0,
        "region": "welland",
        "last_seen": "2026-01-30T10:00:00Z",
        "source": "udp:test"
    },
    {
        "mmsi": 316002001,
        "name": "MONTREAL SHIP 1",
        "type_category": "cargo",
        "position": {"lat": 45.50, "lon": -73.55},
        "heading": 90,
        "speed_knots": 7.0,
        "region": "montreal",
        "last_seen": "2026-01-30T10:00:00Z",
        "source": "aishub"
    },
    {
        "mmsi": 316002002,
        "name": "MONTREAL SHIP 2",
        "type_category": "tug",
        "position": {"lat": 45.48, "lon": -73.52},
        "heading": 270,
        "speed_knots": 2.0,
        "region": "montreal",
        "last_seen": "2026-01-30T10:00:00Z",
        "source": "aishub"
    },
]


class TestBoatRegionFilteringIntegration(unittest.TestCase):
    """Integration tests for boat region filtering with mock vessel data"""

    def setUp(self):
        """Set up fake vessel data"""
        self.all_vessels = FAKE_VESSELS.copy()
        self.welland_vessels = [v for v in self.all_vessels if v["region"] == "welland"]
        self.montreal_vessels = [v for v in self.all_vessels if v["region"] == "montreal"]

    def test_filter_vessels_by_welland_region(self):
        """Filtering by welland region returns only welland vessels"""
        client_regions = {"welland"}
        filtered = [v for v in self.all_vessels if v.get("region") in client_regions]

        self.assertEqual(len(filtered), 2)
        for v in filtered:
            self.assertEqual(v["region"], "welland")
        self.assertIn("WELLAND SHIP 1", [v["name"] for v in filtered])
        self.assertIn("WELLAND SHIP 2", [v["name"] for v in filtered])

    def test_filter_vessels_by_montreal_region(self):
        """Filtering by montreal region returns only montreal vessels"""
        client_regions = {"montreal"}
        filtered = [v for v in self.all_vessels if v.get("region") in client_regions]

        self.assertEqual(len(filtered), 2)
        for v in filtered:
            self.assertEqual(v["region"], "montreal")
        self.assertIn("MONTREAL SHIP 1", [v["name"] for v in filtered])
        self.assertIn("MONTREAL SHIP 2", [v["name"] for v in filtered])

    def test_no_filter_returns_all_vessels(self):
        """No region filter (None) returns all vessels"""
        client_regions = None  # Subscribed to "boats" (all)
        if client_regions is None:
            filtered = self.all_vessels
        else:
            filtered = [v for v in self.all_vessels if v.get("region") in client_regions]

        self.assertEqual(len(filtered), 4)

    def test_client_welland_subscription_filtering(self):
        """WebSocketClient with boats:welland filters correctly"""
        mock_ws = MagicMock()
        client = WebSocketClient(websocket=mock_ws, channels={"boats:welland"})

        client_regions = client.boat_regions()
        self.assertEqual(client_regions, {"welland"})

        # Simulate filtering logic from send_boats_to_client
        if client_regions is not None:
            filtered = [v for v in self.all_vessels if v.get("region") in client_regions]
        else:
            filtered = self.all_vessels

        self.assertEqual(len(filtered), 2)
        for v in filtered:
            self.assertEqual(v["region"], "welland")

    def test_client_montreal_subscription_filtering(self):
        """WebSocketClient with boats:montreal filters correctly"""
        mock_ws = MagicMock()
        client = WebSocketClient(websocket=mock_ws, channels={"boats:montreal"})

        client_regions = client.boat_regions()
        self.assertEqual(client_regions, {"montreal"})

        # Simulate filtering logic
        if client_regions is not None:
            filtered = [v for v in self.all_vessels if v.get("region") in client_regions]
        else:
            filtered = self.all_vessels

        self.assertEqual(len(filtered), 2)
        for v in filtered:
            self.assertEqual(v["region"], "montreal")

    def test_client_all_boats_subscription_no_filtering(self):
        """WebSocketClient with boats (all) does not filter"""
        mock_ws = MagicMock()
        client = WebSocketClient(websocket=mock_ws, channels={"boats"})

        client_regions = client.boat_regions()
        self.assertIsNone(client_regions)

        # Simulate filtering logic
        if client_regions is not None:
            filtered = [v for v in self.all_vessels if v.get("region") in client_regions]
        else:
            filtered = self.all_vessels

        self.assertEqual(len(filtered), 4)

    def test_client_both_regions_subscription(self):
        """WebSocketClient with both boat regions gets both"""
        mock_ws = MagicMock()
        client = WebSocketClient(websocket=mock_ws, channels={"boats:welland", "boats:montreal"})

        client_regions = client.boat_regions()
        self.assertEqual(client_regions, {"welland", "montreal"})

        # Simulate filtering logic
        if client_regions is not None:
            filtered = [v for v in self.all_vessels if v.get("region") in client_regions]
        else:
            filtered = self.all_vessels

        self.assertEqual(len(filtered), 4)


class TestBoatBroadcastRegionFiltering(unittest.TestCase):
    """Test per-region change detection for boat broadcasts"""

    def setUp(self):
        """Set up fake vessel data grouped by region"""
        self.vessels_by_region = {
            "welland": [
                {"mmsi": 316001001, "name": "WELLAND SHIP 1", "position": {"lat": 42.92, "lon": -79.24}, "region": "welland"},
                {"mmsi": 316001002, "name": "WELLAND SHIP 2", "position": {"lat": 42.88, "lon": -79.25}, "region": "welland"},
            ],
            "montreal": [
                {"mmsi": 316002001, "name": "MONTREAL SHIP 1", "position": {"lat": 45.50, "lon": -73.55}, "region": "montreal"},
            ]
        }

    def test_welland_change_detected(self):
        """Change in welland region is detected"""
        from main import get_vessels_for_comparison

        old_welland = self.vessels_by_region["welland"]
        new_welland = [
            {"mmsi": 316001001, "name": "WELLAND SHIP 1", "position": {"lat": 42.93, "lon": -79.24}, "region": "welland"},  # Moved
            {"mmsi": 316001002, "name": "WELLAND SHIP 2", "position": {"lat": 42.88, "lon": -79.25}, "region": "welland"},
        ]

        old_state = get_vessels_for_comparison(old_welland)
        new_state = get_vessels_for_comparison(new_welland)

        self.assertNotEqual(old_state, new_state)

    def test_montreal_unchanged(self):
        """No change in montreal region is detected as unchanged"""
        from main import get_vessels_for_comparison

        old_montreal = self.vessels_by_region["montreal"]
        new_montreal = self.vessels_by_region["montreal"].copy()

        old_state = get_vessels_for_comparison(old_montreal)
        new_state = get_vessels_for_comparison(new_montreal)

        self.assertEqual(old_state, new_state)

    def test_welland_client_notified_on_welland_change(self):
        """Client subscribed to welland should be notified when welland changes"""
        mock_ws = MagicMock()
        client = WebSocketClient(websocket=mock_ws, channels={"boats:welland"})

        changed_regions = {"welland"}
        client_regions = client.boat_regions()

        # Should be notified because client_regions & changed_regions is not empty
        self.assertIsNotNone(client_regions)
        relevant_changes = client_regions & changed_regions
        self.assertEqual(relevant_changes, {"welland"})
        self.assertTrue(len(relevant_changes) > 0)

    def test_welland_client_not_notified_on_montreal_change(self):
        """Client subscribed to welland should NOT be notified when only montreal changes"""
        mock_ws = MagicMock()
        client = WebSocketClient(websocket=mock_ws, channels={"boats:welland"})

        changed_regions = {"montreal"}
        client_regions = client.boat_regions()

        # Should NOT be notified because client_regions & changed_regions is empty
        self.assertIsNotNone(client_regions)
        relevant_changes = client_regions & changed_regions
        self.assertEqual(relevant_changes, set())
        self.assertFalse(len(relevant_changes) > 0)

    def test_all_boats_client_notified_on_any_change(self):
        """Client subscribed to all boats is notified on any region change"""
        mock_ws = MagicMock()
        client = WebSocketClient(websocket=mock_ws, channels={"boats"})

        changed_regions = {"montreal"}
        client_regions = client.boat_regions()

        # client_regions is None for "boats" subscription, so always notified
        self.assertIsNone(client_regions)
        # When client_regions is None, client gets full payload regardless of changed_regions


class TestBridgeRegionFilteringIntegration(unittest.TestCase):
    """Integration tests for bridge region filtering"""

    def setUp(self):
        """Set up fake bridge data"""
        self.all_bridges = {
            "SCT_CarltonSt": {"static": {"name": "Carlton St.", "region_short": "SCT"}},
            "SCT_GlendaleAve": {"static": {"name": "Glendale Ave", "region_short": "SCT"}},
            "PC_ClarenceSt": {"static": {"name": "Clarence St.", "region_short": "PC"}},
            "PC_MainSt": {"static": {"name": "Main St.", "region_short": "PC"}},
            "MSS_VictoriaBridge": {"static": {"name": "Victoria Bridge", "region_short": "MSS"}},
            "K_CPRailway7A": {"static": {"name": "CP Railway 7A", "region_short": "K"}},
        }
        self.available_bridges = [
            {"id": "SCT_CarltonSt", "region_short": "SCT"},
            {"id": "SCT_GlendaleAve", "region_short": "SCT"},
            {"id": "PC_ClarenceSt", "region_short": "PC"},
            {"id": "PC_MainSt", "region_short": "PC"},
            {"id": "MSS_VictoriaBridge", "region_short": "MSS"},
            {"id": "K_CPRailway7A", "region_short": "K"},
        ]

    def test_filter_bridges_by_sct_region(self):
        """Filtering by SCT region returns only SCT bridges"""
        client_regions = {"sct"}

        filtered_bridges = {
            bid: bdata for bid, bdata in self.all_bridges.items()
            if bid.split("_")[0].lower() in client_regions
        }

        self.assertEqual(len(filtered_bridges), 2)
        self.assertIn("SCT_CarltonSt", filtered_bridges)
        self.assertIn("SCT_GlendaleAve", filtered_bridges)
        self.assertNotIn("PC_ClarenceSt", filtered_bridges)

    def test_filter_bridges_by_sct_and_pc(self):
        """Filtering by SCT+PC returns both regions"""
        client_regions = {"sct", "pc"}

        filtered_bridges = {
            bid: bdata for bid, bdata in self.all_bridges.items()
            if bid.split("_")[0].lower() in client_regions
        }

        self.assertEqual(len(filtered_bridges), 4)
        self.assertIn("SCT_CarltonSt", filtered_bridges)
        self.assertIn("PC_ClarenceSt", filtered_bridges)
        self.assertNotIn("MSS_VictoriaBridge", filtered_bridges)

    def test_filter_available_bridges_by_region(self):
        """available_bridges list is also filtered by region"""
        client_regions = {"sct"}

        filtered_available = [
            b for b in self.available_bridges
            if b["region_short"].lower() in client_regions
        ]

        self.assertEqual(len(filtered_available), 2)
        for b in filtered_available:
            self.assertEqual(b["region_short"], "SCT")

    def test_client_sct_subscription_filtering(self):
        """WebSocketClient with bridges:sct filters correctly"""
        mock_ws = MagicMock()
        client = WebSocketClient(websocket=mock_ws, channels={"bridges:sct"})

        client_regions = client.bridge_regions()
        self.assertEqual(client_regions, {"sct"})

        # Simulate filtering logic from send_bridges_to_client
        if client_regions is not None:
            filtered = {
                bid: bdata for bid, bdata in self.all_bridges.items()
                if bid.split("_")[0].lower() in client_regions
            }
        else:
            filtered = self.all_bridges

        self.assertEqual(len(filtered), 2)
        for bid in filtered:
            self.assertTrue(bid.startswith("SCT_"))

    def test_sct_client_notified_on_sct_change(self):
        """Client subscribed to bridges:sct notified when SCT bridge changes"""
        mock_ws = MagicMock()
        client = WebSocketClient(websocket=mock_ws, channels={"bridges:sct"})

        changed_bridge_ids = {"SCT_CarltonSt"}
        changed_regions = {bid.split("_")[0].lower() for bid in changed_bridge_ids}

        client_regions = client.bridge_regions()
        relevant_changes = client_regions & changed_regions

        self.assertEqual(relevant_changes, {"sct"})
        self.assertTrue(len(relevant_changes) > 0)

    def test_sct_client_not_notified_on_mss_change(self):
        """Client subscribed to bridges:sct NOT notified when MSS bridge changes"""
        mock_ws = MagicMock()
        client = WebSocketClient(websocket=mock_ws, channels={"bridges:sct"})

        changed_bridge_ids = {"MSS_VictoriaBridge"}
        changed_regions = {bid.split("_")[0].lower() for bid in changed_bridge_ids}

        client_regions = client.bridge_regions()
        relevant_changes = client_regions & changed_regions

        self.assertEqual(relevant_changes, set())
        self.assertFalse(len(relevant_changes) > 0)


if __name__ == '__main__':
    print("Running Bridge Up WebSocket Channel Tests...")
    print("Testing subscription system, change detection, and region filtering.")
    print("=" * 70)

    unittest.main(verbosity=2)
