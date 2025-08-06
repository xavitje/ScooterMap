import tkinter as tk
from tkinter import ttk, messagebox
import osmnx as ox
import networkx as nx
from geopy.geocoders import Nominatim
from tkintermapview import TkinterMapView

ox.settings.log_console = True
ox.settings.use_cache = True
ox.settings.timeout = 300  # 5 minuten timeout


class ScooterNavigator:

    def __init__(self, root):
        print("Scooter Navigator Pro is gestart!")
        self.root = root
        self.root.title("🚀 Scooter Navigator Pro")
        self.root.geometry("1000x800")

        # Adres invoervelden
        self.address_frame = ttk.Frame(root)
        self.address_frame.pack(pady=10, padx=10, fill=tk.X)

        ttk.Label(self.address_frame, text="Startadres:").pack(side=tk.LEFT)
        self.start_address_entry = ttk.Entry(self.address_frame, width=40)
        self.start_address_entry.pack(side=tk.LEFT, padx=5)

        ttk.Label(self.address_frame, text="Eindadres:").pack(side=tk.LEFT)
        self.end_address_entry = ttk.Entry(self.address_frame, width=40)
        self.end_address_entry.pack(side=tk.LEFT, padx=5)

        self.btn_find_address = ttk.Button(self.address_frame,
                                           text="Adressen zoeken",
                                           command=self.locate_addresses)
        self.btn_find_address.pack(side=tk.LEFT)

        # Kaart widget
        self.map_widget = TkinterMapView(root, width=980, height=600)
        self.map_widget.pack(pady=10, padx=10)

        # Markers en route
        self.start_marker = None
        self.end_marker = None
        self.route_line = None

        # Knoppen voor handmatige selectie
        self.control_frame = ttk.Frame(root)
        self.control_frame.pack(pady=10)

        ttk.Button(self.control_frame,
                   text="📌 Handmatig startpunt",
                   command=self.set_start).pack(side=tk.LEFT, padx=5)
        ttk.Button(self.control_frame,
                   text="🏁 Handmatig eindpunt",
                   command=self.set_end).pack(side=tk.LEFT, padx=5)
        ttk.Button(self.control_frame,
                   text="🚀 Route berekenen",
                   command=self.calculate_route,
                   style="Accent.TButton").pack(side=tk.LEFT, padx=5)
        ttk.Button(self.control_frame,
                   text="❌ Alles wissen",
                   command=self.clear_all).pack(side=tk.LEFT, padx=5)

        # Initieel scherm
        self.map_widget.set_position(52.3676, 4.9041)  # Amsterdam
        self.map_widget.set_zoom(14)
        self.geolocator = Nominatim(user_agent="scooter_navigator", timeout=10)

    def locate_addresses(self):
        """Zoek coördinaten voor ingevoerde adressen"""
        try:
            # Startadres zoeken
            start_address = self.start_address_entry.get()
            if start_address:
                start_location = self.geolocator.geocode(start_address +
                                                         ", Nederland")
                if start_location:
                    self.map_widget.set_position(start_location.latitude,
                                                 start_location.longitude)
                    self.set_start_position(start_location.latitude,
                                            start_location.longitude)

            # Eindadres zoeken
            end_address = self.end_address_entry.get()
            if end_address:
                end_location = self.geolocator.geocode(end_address +
                                                       ", Nederland")
                if end_location:
                    self.set_end_position(end_location.latitude,
                                          end_location.longitude)

        except Exception as e:
            messagebox.showerror("Fout", f"Adres niet gevonden: {str(e)}")

    def set_start_position(self, lat, lon):
        """Plaats startmarker op specifieke coördinaten"""
        if self.start_marker:
            self.start_marker.delete()
        self.start_marker = self.map_widget.set_marker(
            lat,
            lon,
            text="Start",
            marker_color_circle="blue",
            marker_color_outside="white",
            text_color="blue")

    def set_end_position(self, lat, lon):
        """Plaats eindmarker op specifieke coördinaten"""
        if self.end_marker:
            self.end_marker.delete()
        self.end_marker = self.map_widget.set_marker(
            lat,
            lon,
            text="Eind",
            marker_color_circle="red",
            marker_color_outside="white",
            text_color="red")

    def set_start(self):
        """Handmatig startpunt instellen via kaartklik"""
        pos = self.map_widget.get_position()
        self.set_start_position(pos[0], pos[1])
        self.start_address_entry.delete(0, tk.END)
        self.start_address_entry.insert(0,
                                        self.reverse_geocode(pos[0], pos[1]))

    def set_end(self):
        """Handmatig eindpunt instellen via kaartklik"""
        pos = self.map_widget.get_position()
        self.set_end_position(pos[0], pos[1])
        self.end_address_entry.delete(0, tk.END)
        self.end_address_entry.insert(0, self.reverse_geocode(pos[0], pos[1]))

    def reverse_geocode(self, lat, lon):
        """Zoek adres bij coördinaten"""
        try:
            location = self.geolocator.reverse(f"{lat}, {lon}")
            return location.address.split(",")[0]  # Korte adresweergave
        except:
            return f"{lat:.5f}, {lon:.5f}"

    def calculate_route(self):
        """Geavanceerde routeberekening voor scooters/brommers."""
        if not (self.start_marker and self.end_marker):
            messagebox.showerror("Fout", "Selecteer eerst start- en eindpunt")
            return

        try:
            start_lat, start_lon = self.start_marker.position
            end_lat, end_lon = self.end_marker.position

            # Download kaartdata met custom filters
            G = ox.graph_from_point(
                (start_lat, start_lon),
                dist=5000,
                custom_filter=('["highway"]["access"!~"private|no"]'
                               '["motor_vehicle"!~"no"]'
                               '["motorcycle"!~"no"]'),
                simplify=True)

            # Wegtype prioritering (aanpasbaar)
            road_priority = {
                'cycleway': 1,  # Fietspaden (hoogste prioriteit)
                'living_street': 2,
                'residential': 3,
                'service': 4,
                'secondary': 5,
                'primary': 6,
                'trunk': 7,
                'motorway': 8  # Vermijden (laagste prioriteit)
            }

            # Pas edge weights aan op basis van wegtype
            for u, v, k, data in G.edges(keys=True, data=True):
                highway_type = data.get('highway', '')
                if isinstance(highway_type, list):
                    highway_type = highway_type[0]

                # Stel gewicht in op basis van prioriteit
                data['weight'] = road_priority.get(highway_type, 5) * data.get(
                    'length', 1)

                # Speciale cases voor NL:
                if 'bicycle_road' in data or 'cyclestreet' in data:
                    data['weight'] *= 0.8  # Geef fietspaden extra gewicht

                if 'moped' in data.get('access', ''):
                    data[
                        'weight'] *= 1.2  # Ontmoedig wegen waar brommers niet mogen

            # Bereken route met aangepaste gewichten
            start_node = ox.nearest_nodes(G, X=[start_lon], Y=[start_lat])[0]
            end_node = ox.nearest_nodes(G, X=[end_lon], Y=[end_lat])[0]

            route = nx.shortest_path(G, start_node, end_node, weight="weight")

            # Visualisatie
            self.draw_route(G, route)

            # Toon route-info
            self.show_route_stats(G, route)

        except Exception as e:
            messagebox.showerror("Fout", f"Fout in routeberekening:\n{str(e)}")

    def draw_route(self, G, route):
        """Teken de route met kleurcodering voor wegtypen"""
        try:
            route_edges = list(zip(route[:-1], route[1:]))
            colors = []

            for u, v in route_edges:
                edge_data = G.get_edge_data(u, v)[0]
                wegtype = edge_data.get('highway', 'road')

                if 'cycleway' in wegtype:
                    colors.append("#4CAF50")  # Groen voor fietspaden
                elif 'residential' in wegtype:
                    colors.append("#FFC107")  # Geel voor woonstraten
                else:
                    colors.append("#2196F3")  # Blauw voor andere wegen

            route_coords = [(G.nodes[node]["y"], G.nodes[node]["x"])
                            for node in route]

            # Verwijder oude route (als die bestaat)
            if self.route_line:
                self.map_widget.delete(self.route_line)

            # Teken nieuwe route (ZONDER arrow=True)
            self.route_line = self.map_widget.set_path(
                route_coords,
                color=colors if len(colors) == len(route_coords) -
                1 else "#2196F3",
                width=5)

            # Voeg eindmarker toe
            if len(route_coords) > 1:
                end_lat, end_lon = route_coords[-1]
                if hasattr(self, 'eind_marker'):
                    self.eind_marker.delete()
                self.eind_marker = self.map_widget.set_marker(
                    end_lat,
                    end_lon,
                    text="Eindpunt",
                    marker_color_circle="red",
                    text_color="black")

        except Exception as e:
            messagebox.showerror("Fout", f"Route weergeven mislukt:\n{str(e)}")

    def show_route_stats(self, G, route):
        """Toon gedetailleerde route-statistieken."""
        total_length = 0
        road_types = {}

        for i in range(len(route) - 1):
            edge_data = G.get_edge_data(route[i], route[i + 1])[0]
            total_length += edge_data['length']
            hw_type = edge_data.get('highway', 'unknown')
            road_types[hw_type] = road_types.get(hw_type,
                                                 0) + edge_data['length']

        stats = "\n".join(
            f"{k}: {v/1000:.1f} km ({v/total_length*100:.0f}%)"
            for k, v in sorted(road_types.items(), key=lambda x: -x[1]))

        messagebox.showinfo(
            "Route-informatie",
            f"Totale afstand: {total_length/1000:.1f} km\n\nWegtypen:\n{stats}"
        )

    def clear_all(self):
        """Wis alle ingevoerde data"""
        self.start_address_entry.delete(0, tk.END)
        self.end_address_entry.delete(0, tk.END)
        if self.start_marker:
            self.start_marker.delete()
            self.start_marker = None
        if self.end_marker:
            self.end_marker.delete()
            self.end_marker = None
        if self.route_line:
            self.route_line.delete()
            self.route_line = None


if __name__ == "__main__":
    root = tk.Tk()
    app = ScooterNavigator(root)
    root.mainloop()
