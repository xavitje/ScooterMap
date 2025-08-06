import folium
from flask import Flask, render_template_string, request
import osmnx as ox
import networkx as nx
from geopy.geocoders import Nominatim
import math
import requests
from geopy.distance import great_circle
import networkx as nx

# OSMnx configuratie
ox.settings.log_console = True
ox.settings.use_cache = True
ox.settings.timeout = 300

app = Flask(__name__)
geolocator = Nominatim(user_agent="scooter_navigator", timeout=10)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>🚀 Scooter Navigator Pro (Web)</title>
    <meta charset="utf-8"/>
    <style>
        body { font-family: Arial, sans-serif; margin: 0; padding: 20px; }
        .container { display: flex; flex-direction: column; height: 100vh; }
        .controls { background: #f0f0f0; padding: 15px; border-radius: 5px; margin-bottom: 10px; }
        #map { flex: 1; border: 1px solid #ccc; border-radius: 5px; }
        input, button { padding: 8px; margin: 5px; }
        button { background: #4285f4; color: white; border: none; cursor: pointer; }
        .route-info { background: #e8f4ff; padding: 10px; border-radius: 5px; margin-top: 10px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="controls">
            <h2>Scooter Navigator Pro</h2>
            <form method="POST">
                <input type="text" name="start_address" placeholder="Startadres" value="{{ start_address }}" size="40">
                <input type="text" name="end_address" placeholder="Eindadres" value="{{ end_address }}" size="40">
                <button type="submit">Route berekenen</button>
            </form>
            {% if route_stats %}
            <div class="route-info">
                <h3>Route-informatie</h3>
                <p>{{ route_stats }}</p>
                <p><strong>Wegtypen:</strong><br>{{ road_types }}</p>
            </div>
            {% endif %}
        </div>
        <div id="map">{{ map_html|safe }}</div>
    </div>
</body>
</html>
"""
class ScooterRoutePlanner:
    def __init__(self):
        self.overpass_url = "https://overpass-api.de/api/interpreter"
        self.graph = nx.Graph()
        self.nodes = {}  # Bewaar node coördinaten

    def _get_osm_data(self, bbox, retry=3):
        """Verbeterde data-fetching met retry-logica"""
        query = f"""
        [out:json][timeout:180];
        (
            way["highway"]["access"!~"no|private"]
            ["motor_vehicle"!~"no"]
            ["motorcycle"!~"no"]
            ({" ".join(bbox)});
            node(w);
        );
        out body;
        >;
        out skel qt;
        """
        for attempt in range(retry):
            try:
                response = requests.post(self.overpass_url, data=query, timeout=30)
                return response.json()
            except Exception as e:
                if attempt == retry-1:
                    raise ValueError(f"Overpass API error: {str(e)}")
                time.sleep(2)

    def calculate_route(self, start_coords, end_coords):
        """Verbeterde routeberekening met fallback"""
        # Vergroot de bounding box (+/- 0.02 graden ~ 2km)
        bbox = [
            f"{min(start_coords[0], end_coords[0])-0.02}",
            f"{min(start_coords[1], end_coords[1])-0.02}",
            f"{max(start_coords[0], end_coords[0])+0.02}",
            f"{max(start_coords[1], end_coords[1])+0.02}"
        ]
        
        data = self._get_osm_data(bbox)
        self._build_graph(data)
        
        start_node = self._find_nearest_node(start_coords)
        end_node = self._find_nearest_node(end_coords)
        
        try:
            # Probeer eerst strikte route (alleen moped=yes)
            node_path = nx.shortest_path(
                self.graph, start_node, end_node,
                weight='weight'
            )
            return self._process_route(node_path)
            
        except nx.NetworkXNoPath:
            # Fallback: probeer minder strikte route
            try:
                node_path = nx.shortest_path(
                    self.graph, start_node, end_node,
                    weight='fallback_weight'
                )
                return self._process_route(node_path, is_fallback=True)
            except:
                raise ValueError("Geen route gevonden, zelfs niet met fallback")

    def _build_graph(self, data):
        """Bouw graaf met extra fallback-logica"""
        for element in data['elements']:
            if element['type'] == 'node':
                self.nodes[element['id']] = (element['lat'], element['lon'])
                
            elif element['type'] == 'way':
                tags = element.get('tags', {})
                is_allowed = self._is_way_allowed(tags)
                
                for i in range(len(element['nodes'])-1):
                    u, v = element['nodes'][i], element['nodes'][i+1]
                    if u in self.nodes and v in self.nodes:
                        # Hoofdgewicht (strikt beleid)
                        weight = 100 if not is_allowed else self._calculate_weight(tags)
                        
                        # Fallback gewicht (minder strikt)
                        fallback_weight = 10 if not is_allowed else 1
                        
                        self.graph.add_edge(
                            u, v,
                            weight=weight,
                            fallback_weight=fallback_weight,
                            coords=(self.nodes[u], self.nodes[v]),
                            tags=tags
                        )

    def _is_way_allowed(self, tags):
        """Bepaal of weg expliciet toegestaan is"""
        name = str(tags.get('name', '')).lower()
        access = str(tags.get('access', '')).lower()
        return (
            'bromfietspad' in name or
            'moped=yes' in access or
            'moped=designated' in access
        )

    def _calculate_weight(self, tags):
        """Gewichtberekening met wegklassen"""
        highway = tags.get('highway', '')
        if highway == 'residential':
            return 2
        elif highway == 'service':
            return 3
        return 1

    def _find_nearest_node(self, coords):
        """Verbeterde nearest-node met KDTree voor snelheid"""
        if not hasattr(self, '_coords_tree'):
            from sklearn.neighbors import KDTree
            self._node_ids = list(self.nodes.keys())
            self._coords_tree = KDTree(list(self.nodes.values()))
        
        _, idx = self._coords_tree.query([coords], k=1)
        return self._node_ids[idx[0][0]]

    def _process_route(self, node_path, is_fallback=False):
        """Converteer node path naar coördinaten en stats"""
        route_coords = []
        allowed_segments = 0
        total_segments = len(node_path)-1
        
        for i in range(total_segments):
            u, v = node_path[i], node_path[i+1]
            if self.graph.has_edge(u, v):
                edge_data = self.graph[u][v]
                route_coords.extend(edge_data['coords'])
                if self._is_way_allowed(edge_data['tags']):
                    allowed_segments += 1
        
        stats = {
            'distance': f"{self._calculate_route_length(route_coords)/1000:.1f} km",
            'quality': f"{(allowed_segments/total_segments)*100:.0f}%",
            'is_fallback': is_fallback
        }
        return route_coords, stats

    def _calculate_route_length(self, coords):
        """Bereken totale route lengte"""
        return sum(great_circle(coords[i], coords[i+1]).meters 
                  for i in range(len(coords)-1))


def analyze_route_quality(G, route):
    """Analyseer hoeveel van de route ideaal is"""
    total_length = 0
    perfect_length = 0
    good_length = 0
    poor_length = 0
    
    for i in range(len(route)-1):
        edge_data = G.get_edge_data(route[i], route[i+1])[0]
        length = edge_data['length']
        total_length += length
        
        if 'bromfietspad' in str(edge_data.get('name', '')).lower():
            perfect_length += length
        elif 'moped=yes' in str(edge_data.get('access', '')).lower():
            good_length += length
        else:
            poor_length += length
    
    return {
        'total': f"{total_length/1000:.1f} km",
        'perfect': f"{(perfect_length/total_length)*100:.0f}%",
        'good': f"{(good_length/total_length)*100:.0f}%",
        'poor': f"{(poor_length/total_length)*100:.0f}%"
    }

def calculate_route_stats(G, route):
    """Bereken route-statistieken"""
    total_length = 0
    road_types = {}
    
    for i in range(len(route)-1):
        edge_data = G.get_edge_data(route[i], route[i+1])[0]
        total_length += edge_data['length']
        hw_type = edge_data.get('highway', 'unknown')
        
        # Oplossing voor lijst als wegtype
        if isinstance(hw_type, list):
            hw_type = hw_type[0] if hw_type else 'unknown'
        
        road_types[hw_type] = road_types.get(hw_type, 0) + edge_data['length']
    
    stats = {
        'distance': f"{total_length/1000:.1f} km",
        'road_types': "\n".join(
            f"{k}: {v/1000:.1f} km ({v/total_length*100:.0f}%)" 
            for k, v in sorted(road_types.items(), key=lambda x: -x[1]))
    }
    return stats

@app.route("/", methods=["GET", "POST"])
def index():
    map_obj = folium.Map(location=[52.3676, 4.9041], zoom_start=14)
    planner = ScooterRoutePlanner()
    messages = []
    
    if request.method == "POST":
        start_address = request.form["start_address"]
        end_address = request.form["end_address"]
        
        try:
            start_coords = get_coordinates(start_address)
            end_coords = get_coordinates(end_address)
            
            if start_coords and end_coords:
                route_coords, stats = planner.calculate_route(start_coords, end_coords)
                
                # Route tekenen
                folium.PolyLine(
                    route_coords,
                    color='orange' if stats['is_fallback'] else 'blue',
                    weight=6 if stats['is_fallback'] else 5,
                    opacity=0.7,
                    tooltip=f"Kwaliteit: {stats['quality']}"
                ).add_to(map_obj)
                
                # Markers
                folium.Marker(start_coords, popup="Start", icon=folium.Icon(color='green')).add_to(map_obj)
                folium.Marker(end_coords, popup="Eind", icon=folium.Icon(color='red')).add_to(map_obj)
                
                map_obj.fit_bounds([start_coords, end_coords])
                messages.append(f"Route: {stats['distance']}")
                messages.append(f"Kwaliteit: {stats['quality']} toegestane wegen")
                if stats['is_fallback']:
                    messages.append("⚠️ Minder optimale route gebruikt")
                
        except Exception as e:
            messages.append(f"Fout: {str(e)}")
            # Toon beschikbare wegen voor debug
            debug_layer = folium.FeatureGroup(name="Beschikbare wegen")
            for u, v, data in planner.graph.edges(data=True):
                folium.PolyLine(
                    data['coords'],
                    color='gray',
                    weight=1,
                    opacity=0.3
                ).add_to(debug_layer)
            debug_layer.add_to(map_obj)
    
    return render_template_string(
        HTML_TEMPLATE,
        map_html=map_obj._repr_html_(),
        start_address=start_address if 'start_address' in locals() else "",
        end_address=end_address if 'end_address' in locals() else "",
        route_stats="<br>".join(messages) if messages else ""
    )

    
    return render_template_string(
        HTML_TEMPLATE,
        map_html=map_obj._repr_html_(),
        start_address=start_address,
        end_address=end_address,
        route_stats=route_stats,
        road_types=road_types
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
