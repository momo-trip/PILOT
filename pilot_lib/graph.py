import json
import os
import time

from collections import defaultdict, deque
from typing import Dict, List, NamedTuple, Set, Tuple

import numpy as np
import networkx as nx
import pandas as pd
from scipy.stats import skew

import clang.cindex
from clang.cindex import (
    CompilationDatabase,
    Index,
)

from utils_api import (
    read_json,
    write_json,
    parse_def_loc,
)

from pilot_lib.utils import (
    get_metadata,
    parse_function_data,
    get_related_data,
    parse_function_id,
    get_metrics,
)


class FunctionId(NamedTuple): # Information to uniquely identify a function"
    name: str
    file_path: str
    line_cov: str
    branch_cov: str

    def __str__(self):
        return f"{self.name} ({self.file_path})"

def get_call_site(name, call_site_list):
    ans = []
    for callee_id in call_site_list:
        callee_name, callee_file_path, call_line = parse_function_id(callee_id)
        if name == callee_name:
            ans.append({
                "callee_file_path" : callee_file_path,
                "call_line" : call_line
            })
    return ans


def get_edge_weight(callee_path, callee_main_path, distance_path):
    
    path_data = []
    result = {} #[]

    functions = read_json(callee_path)
    related_data = get_related_data(callee_main_path)
    
    for key, func_item in functions.items():
        if key not in related_data:
            continue
        call_site_list = func_item['call_sites']
        total = 0
        count = 0
        for item in func_item['callees']:
            source_file = func_item['file_path'] 
            func_a_name = func_item['name']   
            a_start_line = func_item['def_start_line'] 
            a_end_line = func_item['def_end_line'] 

            callee_name, callee_path, callee_line = parse_function_id(item)
            callee_list = get_call_site(callee_name, call_site_list)

            for callee_item in callee_list:
                callee_file_path = callee_item['callee_file_path']
                call_line = callee_item['call_line']

                # if WEIGHT is not None:
                #     weight = analyze_branches_to_call(callee_file_path, func_a_name, a_start_line, a_end_line, callee_name, call_line)      
                
                weight = 1

                total += weight
                count += 1

            edge_weight = total / count if count != 0 else 0

            pair_id = f"{key}@@{item}"
            result[pair_id]= {}
            result[pair_id] = {
                "source" : key,
                "destination" : item,
                "edge_weight" : edge_weight,
                "path_count" : count
            }

        func_item['edge_weight'] = total / count if count != 0 else 0
        func_item['path_count'] = count

    write_json(distance_path, result)


def get_path_weight(path_list, distance):
    """
    Compute and sum the weights between each consecutive pair of nodes in the path list

    Args:
        path_list: A dictionary containing path information (with a node list in the 'path' key)
        function_data: A dictionary containing function information

    Returns:
        float: The total weight of the entire path
    """
    total = 0

    # Sum the weights of each edge (between consecutive nodes) in the path
    for i in range(len(path_list) - 1):
        node_from = path_list[i]
        node_to = path_list[i+1]
        
        get_id = f"{node_from}@@{node_to}"

        # Get the edge weight
        edge_weight = distance[get_id]['edge_weight']
    
        total += edge_weight
        
    return total


def get_total_weight(callee_main_path, distance_path):
    functions = read_json(callee_main_path)
    distance = read_json(distance_path)

    # Aggregate the weights of all paths
    total_weight = 0
    total_paths = 0

    for function in functions:
        if 'all_paths' in function: # and 'edge_weight' in function:
            for i in range(0, len(function['all_paths'])):
                path_list = function['all_paths'][i]['path']
                path_weight = get_path_weight(path_list, distance)
                total_weight += path_weight

        function['total_edge_weight'] = total_weight
    
    # Display the results
    print(f"\nTotal weight of all {total_paths} paths: {total_weight}")

    write_json(callee_main_path, functions)
    return total_weight



def get_weighted_centrality(callee_path, callee_main_path, distance_path):
    """
    Build a graph to compute the weighted centrality metrics of functions
    
    Args:
        callee_main_path: JSON (dictionary) storing the function relationship information
        distance_path: JSON (list) storing the edge weight information
    
    Returns:
        tuple: (G, metrics_dict) - A tuple containing the graph and the dictionary of centrality metrics
    """
    
    # Load from JSON (use as is if already a dict/list)
    callee_data = read_json(callee_path)
    distance_data = read_json(distance_path)
    related_ids = get_related_data(callee_main_path)

    # Create a weighted directed graph
    G = nx.DiGraph()
    
    # 1. Add nodes (from the function information)
    for func_id, func_info in callee_data.items():
        if func_id not in related_ids:
            continue
        G.add_node(
            func_id, 
            name=func_info.get('name', ''),
            file_path=func_info.get('file_path', ''),
            start_line=func_info.get('def_start_line', 0)
        )
    
    # 2. Add edges (get the weight information from distance_path)
    edge_weights = {}
    for func_key, edge_info in distance_data.items():
        source = edge_info['source']
        dest = edge_info['destination']
        weight = edge_info['edge_weight']
        
        # Store the weight keyed by (source, dest)
        edge_weights[(source, dest)] = weight
        
        # Add the edge to the graph
        if source in G and dest in G:
            G.add_edge(source, dest, weight=weight)
    
    # 3. Add edges from the function call relationships (default value 1.0 if no weight is found)
    for func_id, func_info in callee_data.items():
        if 'callees' in func_info:
            for callee in func_info['callees']:
                if (func_id, callee) not in edge_weights:
                    G.add_edge(func_id, callee, weight=1.0)
    
    # 4. Compute the weighted centrality metrics
    metrics = {
        'in_degree': {},
        'out_degree': {},
        'closeness_centrality': {},
        'betweenness_centrality': {},
        'pagerank': {},
        'katz_centrality': {}
    }
    
    # a. Weighted degree centrality (in and out)
    for node in G.nodes():
        # In-degree centrality (number of times called and weight)
        in_edges = G.in_edges(node, data=True)
        metrics['in_degree'][node] = sum(edge[2].get('weight', 1.0) for edge in in_edges)
        
        # Out-degree centrality (number of times calling and weight)
        out_edges = G.out_edges(node, data=True)
        metrics['out_degree'][node] = sum(edge[2].get('weight', 1.0) for edge in out_edges)
    
    # Normalization (optional)
    max_in = max(metrics['in_degree'].values()) if metrics['in_degree'] else 1.0
    max_out = max(metrics['out_degree'].values()) if metrics['out_degree'] else 1.0
    
    for node in G.nodes():
        metrics['in_degree'][node] /= max_in
        metrics['out_degree'][node] /= max_out
    
    # b. Weighted closeness centrality
    try:
        metrics['closeness_centrality'] = nx.closeness_centrality(
            G, distance='weight', wf_improved=True
        )
    except:
        # Compute individually in the case of a disconnected graph
        for node in G.nodes():
            try:
                # Compute the shortest path length from each node
                path_lengths = nx.single_source_dijkstra_path_length(G, node, weight='weight')
                if len(path_lengths) > 1:  # Exclude isolated nodes
                    metrics['closeness_centrality'][node] = (len(path_lengths) - 1) / sum(path_lengths.values())
                else:
                    metrics['closeness_centrality'][node] = 0.0
            except:
                metrics['closeness_centrality'][node] = 0.0
    
    # c. Weighted betweenness centrality
    try:
        metrics['betweenness_centrality'] = nx.betweenness_centrality(
            G, weight='weight', normalized=True
        )
    except:
        metrics['betweenness_centrality'] = {node: 0.0 for node in G.nodes()}
    
    # d. Weighted PageRank
    try:
        metrics['pagerank'] = nx.pagerank(
            G, alpha=0.85, weight='weight'
        )
    except:
        metrics['pagerank'] = {node: 0.0 for node in G.nodes()}
    
    # e. Weighted Katz centrality
    try:
        # Get the adjacency matrix
        A = nx.adjacency_matrix(G, weight='weight').todense()
        
        # Compute the alpha parameter (a value slightly smaller than the reciprocal of the largest eigenvalue)
        try:
            eigvals = np.linalg.eigvals(A)
            max_eigval = max(abs(val) for val in eigvals)
            alpha = 0.85 / max_eigval if max_eigval > 0 else 0.1
        except:
            # Use the default value if the eigenvalue computation fails
            alpha = 0.1
        
        # Compute the Katz centrality
        metrics['katz_centrality'] = nx.katz_centrality(
            G, alpha=alpha, beta=1.0, weight='weight', normalized=True
        )
    except Exception as e:
        print(f"An error occurred while computing Katz centrality: {e}")
        # Set default values if an error occurs
        metrics['katz_centrality'] = {node: 0.0 for node in G.nodes()}
    
    # Return a tuple of the graph and the metrics dictionary
    return G, metrics


def get_node_metric(G, metrics, node_id):
    """
    Get the centrality metrics of a specific node
    
    Args:
        graph_and_metrics: A tuple (G, metrics) returned from get_weighted_centrality
        node_id: The node ID
        
    Returns:
        dict: The centrality metrics of the node
    """
    #G, metrics = graph_and_metrics
    
    if node_id not in G:
        return None
    
    node_info = G.nodes[node_id]
    name = node_info.get('name', node_id.split('@')[0] if '@' in node_id else node_id)
    
    result = {
        #'name': name,
        #'file_path': node_info.get('file_path', ''),
        #'start_line': node_info.get('start_line', 0),
        'in_degree': metrics['in_degree'].get(node_id, 0.0),
        'out_degree': metrics['out_degree'].get(node_id, 0.0),
        'closeness_centrality': metrics['closeness_centrality'].get(node_id, 0.0),
        'betweenness_centrality': metrics['betweenness_centrality'].get(node_id, 0.0),
        'pagerank': metrics['pagerank'].get(node_id, 0.0),
        'katz_centrality': metrics['katz_centrality'].get(node_id, 0.0)
    }
    
    return result



def write_weighted_centrality(callee_path, callee_main_path, distance_path):

    G, metrics = get_weighted_centrality(callee_path, callee_main_path, distance_path)

    # 2. Display simple statistics of the graph structure
    print(f"Number of nodes: {G.number_of_nodes()}")
    print(f"Number of edges: {G.number_of_edges()}")
    
    # 3. Get the centrality metrics of specific nodes
    functions = read_json(callee_main_path)
    for item in functions:
        func_id = item['function_id']
        node_metrics = get_node_metric(G, metrics, func_id)
        item['metrics'] = node_metrics
        
    write_json(callee_main_path, functions)



def _build_graph(function_data): #, callee_main_path):
    """
    Build a graph from the function data
    
    Args:
        function_data (dict): Data containing the dependencies between functions
        
    Returns:
        tuple: (forward_graph, backward_graph)
        - forward_graph: A graph from a function to its callees (key->callees)
        - backward_graph: A graph from a function to its callers (key->callers)
    """
    forward_graph = defaultdict(list)  # function -> callees
    backward_graph = defaultdict(list)  # function -> callers
    
    # related_ids = get_related_data(callee_main_path)

    for func_id, func_info in function_data.items():
        # if func_id not in related_ids:
        #     continue

        # Add the callee functions
        if "callees" in func_info:
            forward_graph[func_id].extend(func_info["callees"])
        
        # Add the caller functions
        if "callers" in func_info:
            backward_graph[func_id].extend(func_info["callers"])
    
    return forward_graph, backward_graph



def _get_function_details(function_id, function_data):
    """
    Get the detailed information from a function ID
    
    Args:
        function_id (str): The function ID
        function_data (dict): The function data
        
    Returns:
        dict: The detailed information of the function
    """
    if function_id not in function_data:
        return {
            "function_id": function_id,
            "name": function_id,
            "file_path": "unknown",
            "start_line": 0,
            "end_line": 0
        }
    
    info = function_data[function_id]
    return {
        "function_id": function_id,
        "name": info.get("name", function_id),
        "file_path": info.get("file_path", "unknown"),
        "start_line": info.get("def_start_line", 0),
        "end_line": info.get("def_end_line", 0)
    }


def get_all_related_functions(callee_path, function_id, database_dir, callee_main_path):
    """
    Use graph theory to find all functions reachable from a specific function,
    and also include the shortest path information to each of them
    
    Args:
        function_data (dict): Data containing the dependencies between functions
        function_id (str): The ID of the function to analyze
        callee_main_path (str): The path of the JSON file to write the results to
        
    Returns:
        dict: A dictionary containing the information of the related functions
    """
    function_data = read_json(callee_path)
    if function_id not in function_data:
        print(f"Function not found: {function_id}")
        return {"callers": [], "callees": [], "all_related": []}
    
    # Build the graph
    forward_graph, backward_graph = _build_graph(function_data) #, callee_main_path)
    
    # Data structure to store the results
    result = {
        "callers": [],
        "callees": [],
        "all_related": []
    }
    
    # Find the shortest paths with BFS (forward direction - callees)
    def _find_shortest_paths_forward(start_node):
        visited = {start_node: [start_node]}  # node -> the shortest path to that node
        queue = deque([start_node])
        
        while queue:
            node = queue.popleft()
            current_path = visited[node]
            
            for neighbor in forward_graph.get(node, []):
                if neighbor not in visited:
                    new_path = current_path + [neighbor]
                    visited[neighbor] = new_path
                    queue.append(neighbor)
        
        return visited
    
    # Find the shortest paths with BFS (backward direction - callers)
    def _find_shortest_paths_backward(start_node):
        visited = {start_node: [start_node]}  # node -> the shortest path to that node
        queue = deque([start_node])
        
        while queue:
            node = queue.popleft()
            current_path = visited[node]
            
            for neighbor in backward_graph.get(node, []):
                if neighbor not in visited:
                    new_path = current_path + [neighbor]
                    visited[neighbor] = new_path
                    queue.append(neighbor)
        
        return visited
    
    # Find the paths
    forward_paths = _find_shortest_paths_forward(function_id)
    backward_paths = _find_shortest_paths_backward(function_id)
    
    # Get the direct callees from forward_paths
    for callee_id in forward_graph.get(function_id, []):
        if callee_id == function_id:
            continue
            
        details = _get_function_details(callee_id, function_data)
        details["relationship"] = "calls"
        
        # Add the path information
        path = forward_paths.get(callee_id, [function_id, callee_id])
        details["path"] = [function_data[p].get("name", p) if p in function_data else p for p in path]
        
        result["callees"].append(details)
    
    # Get the direct callers from backward_paths
    for caller_id in backward_graph.get(function_id, []):
        if caller_id == function_id:
            continue
            
        details = _get_function_details(caller_id, function_data)
        details["relationship"] = "called_by"
        
        # Add the path information
        path = backward_paths.get(caller_id, [function_id, caller_id])
        details["path"] = [function_data[p].get("name", p) if p in function_data else p for p in path]
        
        result["callers"].append(details)
    
    # Information of the original function itself
    self_info = _get_function_details(function_id, function_data)
    self_info["relationship"] = "self"
    self_info["path"] = [function_data[function_id].get("name", function_id)]
    result["all_related"].append(self_info)
    
    # All reachable functions (including direct callees/callers)
    processed = {function_id}  # To avoid duplicates
    
    # Process all reachable callees
    for func_id, path in forward_paths.items():
        if func_id in processed or func_id == function_id:
            continue
            
        processed.add(func_id)
        details = _get_function_details(func_id, function_data)
        
        # Set the relationship type
        if func_id in backward_paths:
            details["relationship"] = "bidirectional"
        else:
            details["relationship"] = "forward_reachable"
        
        # Add the path information
        details["path"] = [function_data[p].get("name", p) if p in function_data else p for p in path]
        
        result["all_related"].append(details)
    
    # Process all reachable callers
    for func_id, path in backward_paths.items():
        if func_id in processed or func_id == function_id:
            continue
            
        processed.add(func_id)
        details = _get_function_details(func_id, function_data)
        
        # Set the relationship type (skip the ones already processed in forward)
        details["relationship"] = "backward_reachable"
        
        # Add the path information
        details["path"] = [function_data[p].get("name", p) if p in function_data else p for p in path]
        
        result["all_related"].append(details)
    
    # Write the results to JSON
    output_data = {
        "function_id": function_id,
        "name": function_data[function_id].get("name", function_id),
        "total_related": len(result["all_related"]),
        "direct_callers": len(result["callers"]),
        "direct_callees": len(result["callees"]),
        "callees": result["callees"],
        "callers": result["callers"],
        "all_related": result["all_related"]
    }
    
    # Write to the JSON file
    write_json(f"{database_dir}/related_sum.json", result)

    with open(callee_main_path, 'w', encoding='utf-8') as f:
        json.dump(output_data['all_related'], f, indent=4, ensure_ascii=False)
    
    return result


def get_bound(meta_dir, file_path, target_function_name, target_line):
    start_line = None
    end_line = None
    meta_data, meta_path = get_metadata(file_path, meta_dir, None)
    for key, item in meta_data.items():
        if (item['start_line'] <= target_line and 
            target_line <= item['end_line'] and 
            target_function_name == item['name']
            ):

            start_line = item['start_line']
            end_line = item['end_line']
            break

    return start_line, end_line




def find_function_relationship_bidirectional(function_data, function_a, function_b):
    """
    Calculate the number of steps needed to reach from function_a to function_b
    using both caller and callee relationships in the given function_data.
    
    Args:
        function_data (dict): JSON data containing function relationship information
        function_a (str): ID of the starting function
        function_b (str): ID of the target function
    
    Returns:
        tuple: (steps, path, direction) where:
               steps is the number of steps to reach from A to B, or -1 if not reachable
               path is a list of function IDs showing the path from A to B
               direction is a list of strings indicating the relationship direction for each step
                 "calls" means the function calls the next one
                 "called_by" means the function is called by the next one
    """
    # Helper function to get function name for a given ID
    def get_function_name(func_id):
        if func_id in function_data:
            return function_data[func_id].get("name", func_id)
        return func_id
    
    # Check if the function IDs exist in data
    if function_a not in function_data or function_b not in function_data:
        print(f"One or both functions not found. A: {function_a}, B: {function_b}")
        return -1, [], []
    
    # If A and B are the same function
    if function_a == function_b:
        return 0, [get_function_name(function_a)], []
    
    # BFS to find the shortest path
    visited = set()
    # (function_id, steps, path, direction)
    queue = [(function_a, 0, [function_a], [])]
    
    while queue:
        current_func_id, steps, path, directions = queue.pop(0)
        
        if current_func_id in visited:
            continue
        
        visited.add(current_func_id)
        
        # Check if we've reached the target
        if current_func_id == function_b:
            # Convert IDs to names for better readability
            named_path = [get_function_name(func_id) for func_id in path]
            return steps, named_path, directions
        
        # Try both directions: callees (functions called by current function)
        current_func = function_data.get(current_func_id, {})
        callees = current_func.get("callees", [])
        
        for callee in callees:
            if callee in function_data and callee not in visited:
                queue.append((callee, steps + 1, path + [callee], directions + ["calls"]))
        
        # And callers (functions that call the current function)
        for func_id, func_info in function_data.items():
            callers = func_info.get("callers", [])
            if current_func_id in callers and func_id not in visited:
                queue.append((func_id, steps + 1, path + [func_id], directions + ["called_by"]))
    
    # If we've exhausted the search without finding B
    return -1, [], []


def find_shortest_path(function_data, function_a, function_b):
    """
    Finds the shortest path between function_a and function_b regardless of direction.
    
    Args:
        function_data (dict): JSON data containing function relationship information
        function_a (str): ID of the starting function
        function_b (str): ID of the target function
        
    Returns:
        tuple: (steps, path, directions, relationship_type) where:
               steps is the number of steps to reach between A and B, or -1 if not reachable
               path is a list of function names showing the path
               directions is a list of direction strings
               relationship_type is one of:
                 "direct" - A calls B directly or indirectly
                 "inverse" - B calls A directly or indirectly
                 "bidirectional" - A and B call each other
                 "none" - No relationship exists
    """
    # Check if the functions exist
    if function_a not in function_data or function_b not in function_data:
        print(f"One or both functions not found. A: {function_a}, B: {function_b}")
        return -1, [], [], "none"
    
    # Check if A and B are the same
    if function_a == function_b:
        name = function_data[function_a].get("name", function_a)
        return 0, [name], [], "same"

    # Check A to B direction
    steps_a_to_b, path_a_to_b, directions_a_to_b = find_function_relationship_bidirectional(
        function_data, function_a, function_b
    )
    
    # Check B to A direction
    steps_b_to_a, path_b_to_a, directions_b_to_a = find_function_relationship_bidirectional(
        function_data, function_b, function_a
    )
    
    # Determine the relationship type and return the shortest path
    if steps_a_to_b != -1 and steps_b_to_a != -1:
        # Both directions have paths
        if steps_a_to_b <= steps_b_to_a:
            return steps_a_to_b, path_a_to_b, directions_a_to_b, "bidirectional"
        else:
            # Reverse the path and directions
            return steps_b_to_a, list(reversed(path_b_to_a)), ["calls" if d == "called_by" else "called_by" for d in reversed(directions_b_to_a)], "bidirectional"
    elif steps_a_to_b != -1:
        # Only A to B has a path
        return steps_a_to_b, path_a_to_b, directions_a_to_b, "direct"
    elif steps_b_to_a != -1:
        # Only B to A has a path
        # Reverse the path and directions
        return steps_b_to_a, list(reversed(path_b_to_a)), ["calls" if d == "called_by" else "called_by" for d in reversed(directions_b_to_a)], "inverse"
    else:
        # No path in either direction
        return -1, [], [], "none"



def find_all_paths_one_direction(function_data, start, target, max_paths=10):  # Restrict even more strictly
    """
    Ultra safe BFS version with strict limits to prevent memory issues
    """
    
    print(f"\nStarting ultra-safe BFS: {start} -> {target}")
    start_time = time.time()
    
    all_paths = []
    queue = deque()
    
    # Stricter limits
    MAX_QUEUE_SIZE = 1000      # Queue size limit
    MAX_ITERATIONS = 5000      # Iteration count limit
    MAX_PATH_LENGTH = 100      # Path length limit (even shorter)
    MAX_CALLEES_PER_FUNC = 100  # Limit on the number of callees explored from one function
    TIMEOUT_SECONDS = 30       # Timeout
    
    # Initialize starting state
    try:
        start_func_name = function_data[start].get("name", start)
        if "@" in start_func_name:
            start_func_name = start_func_name.split("@")[0]
        
        start_name, start_file_path, start_line = parse_function_id(start)
        initial_path = [f"{start_func_name}@{start_file_path}:{start_line}"]
        
        queue.append((start, initial_path, [], [start_file_path], [start_line]))
    except Exception as e:
        print(f"Error parsing start function: {start} - {e}")
        return [], []
    
    # Track visited states more efficiently
    visited_functions = set()  # Record only the visited functions (more lightweight)
    iterations = 0
    
    while queue and len(all_paths) < max_paths and iterations < MAX_ITERATIONS:
        iterations += 1
        
        # Timeout check
        if time.time() - start_time > TIMEOUT_SECONDS:
            print(f"Timeout after {TIMEOUT_SECONDS} seconds")
            break
        
        # Progress display
        if iterations % 500 == 0:
            elapsed = time.time() - start_time
            # print(f"Iteration {iterations}, Queue size: {len(queue)}, Paths found: {len(all_paths)}, Time: {elapsed:.1f}s")
        
        # Queue size limit
        if len(queue) > MAX_QUEUE_SIZE:
            print(f"Queue size limit exceeded ({MAX_QUEUE_SIZE}), trimming...")
            # Reduce the queue by half (prioritize shorter paths)
            temp_queue = list(queue)
            temp_queue.sort(key=lambda x: len(x[1]))  # Sort by path length
            queue = deque(temp_queue[:MAX_QUEUE_SIZE//2])
        
        current, path, directions, call_files, call_lines = queue.popleft()
        
        # Check if we've reached the target
        if current == target:
            all_paths.append({
                "path": path.copy(),
                "directions": directions.copy(),
                "call_files": call_files.copy(),
                "call_lines": call_lines.copy()
            })
            # print(f"Found path #{len(all_paths)}: {' -> '.join([p.split('@')[0] for p in path])}")
            continue
        
        # Skip if path is too long
        if len(path) > MAX_PATH_LENGTH:
            continue
        
        # Do not explore already visited functions again (stricter limit)
        if current in visited_functions:
            continue
        visited_functions.add(current)
        
        # Explore callees
        if current in function_data and "callees" in function_data[current]:
            callees = function_data[current]["callees"]
            
            # Strictly limit the number of callees
            if len(callees) > MAX_CALLEES_PER_FUNC:
                callees = callees[:MAX_CALLEES_PER_FUNC]
            
            for callee in callees:
                callee_id = callee
                
                if callee_id not in function_data:
                    continue
                
                # Skip already visited functions
                if callee_id in visited_functions:
                    continue
                
                # Also skip if it is already included in the current path
                if any(callee_id in p for p in path):
                    continue
                
                try:
                    callee_name, callee_file_path, call_line = parse_function_id(callee_id)
                except:
                    continue
                
                # Create new state
                new_path = path + [f"{callee_name}@{callee_file_path}:{call_line}"]
                new_directions = directions + ["calls"]
                new_call_files = call_files + [callee_file_path]
                new_call_lines = call_lines + [call_line]
                
                queue.append((callee_id, new_path, new_directions, new_call_files, new_call_lines))
    
    elapsed = time.time() - start_time
    # print(f"BFS completed: {iterations} iterations, {elapsed:.2f}s, {len(all_paths)} paths found")
    
    # Sort paths by length
    all_paths.sort(key=lambda x: len(x["path"]))
    
    return all_paths, []



def find_all_paths(function_data, function_a, function_b):
    """
    Finds all possible paths from function_a to function_b without a depth limit.
    Only searches in the direction from A to B (A calls B).
    
    Args:
        function_data (dict): JSON data containing function relationship information
        function_a (str): ID of the starting function
        function_b (str): ID of the target function
    
    Returns:
        list: List of path objects, each containing:
            - path: List of function names showing the path
            - directions: List of direction strings (calls)
            - call_lines: List of line numbers where the calls occur
    """
    # Check if the functions exist
    if function_a not in function_data or function_b not in function_data:
        print(f"One or both functions not found. A: {function_a}, B: {function_b}")
        return []
    
    # Check if A and B are the same
    if function_a == function_b:
        name = function_data[function_a].get("name", function_a)
        return [{"path": [name], "directions": [], "call_files": [], "call_lines": []}], []
    
    # Find all paths from A to B
    return find_all_paths_one_direction(function_data, function_a, function_b)


def get_related_main(
    program_dir, database_json, target_cmd, CURRENT_PATH, 
    work_dir, callee_main_path, callee_path, distance_path, 
    meta_dir, database_dir
):
    """Take the main target function, find all functions related to it and the paths from main, compute edge weights and weighted centrality, and write the results out"""
    
    target_entry = get_main_info(program_dir, database_json, target_cmd, CURRENT_PATH, work_dir, meta_dir, "raw")

    # Collect the dep information of target_entry in advance
    target_path = target_entry['target_path']
    target_line = target_entry['target_line']
    target_function_name = target_entry['target_function']

    start_line, end_line = get_bound(meta_dir, target_path, target_function_name, target_line)
    
    target = {
        "file_path" : target_path,
        "start_line" : start_line,
        "end_line" : end_line,
        "name" : target_function_name
    }

    functions = []
    target_key = f"{target_function_name}@{target_path}:{start_line}"
    get_all_related_functions(callee_path, target_key, database_dir, callee_main_path)

    call_graph = read_json(callee_path)
    functions = read_json(callee_main_path)

    # Measure the degree
    for call in functions:
        if not (target['file_path'] == call['file_path'] and 
                target['start_line'] == call['start_line'] and 
                target['name'] == call['name']):
            
            func_a = f"{target['name']}@{target['file_path']}:{target['start_line']}"
            func_b = f"{call['name']}@{call['file_path']}:{call['start_line']}"

            steps, path, directions, rel_type = find_shortest_path(call_graph, func_a, func_b)
            all_paths, call_site_list = find_all_paths(call_graph, func_a, func_b)
            call['all_paths'] = all_paths
            call['call_site_list'] = call_graph[func_a]['call_sites']

            if steps == -1:
                print("No relationship found between the functions")
            else:
                # print(f"Relationship type: {rel_type}")
                # print(f"Steps required: {steps}")
                print("Path:")
                for i in range(len(path)-1):
                    print(f"  {path[i]} {directions[i]} {path[i+1]}")
                    # print(f"Route: {' -> '.join(path)}")
            
        else:
            # This is the main function itself
            #call['dep_degree'] = 0
            print("Main function itsef")
    
    write_json(callee_main_path, functions)

    get_edge_weight(callee_path, callee_main_path, distance_path)

    get_total_weight(callee_main_path, distance_path)

    write_weighted_centrality(callee_path, callee_main_path, distance_path)



def build_relationship(function_metadata):
    """
    Build a call graph containing callers and callees information from function metadata
    Uses function name, file path, and start line as a composite key to handle functions with the same name
    
    Args:
        function_metadata: A list of JSON metadata
    
    Returns:
        A dictionary keyed by the function's unique identifier, with the function information as the value
    """
    # Step 1: Collect the basic information of the functions
    functions = {}
    func_id_to_info = {}  # Mapping from function ID to function information
    name_to_ids = {}      # Mapping from function name to a list of function IDs
    
    for item in function_metadata:
        if item.get('category') == 'function':
            # Create the function's unique identifier (combination of name, file, and line number)
            func_name = item['name']
            file_path = item.get('def_file_path', '')
            start_line = item.get('def_start_line', 0)
            
            # Generate the unique identifier (including the file path and line number)
            func_id = f"{func_name}@{file_path}:{start_line}"
            
            # Save the function information
            func_info = {
                'id': func_id,
                'name': func_name,
                'signature': item.get('signature', ''),
                'file_path': file_path,
                'is_static': item.get('is_static', False),
                'def_start_line': start_line,
                'def_end_line': item.get('def_end_line'),
                'callers': [],  # List of functions that call this function (built later)
                'callees': [],   # List of functions that this function calls (built later)
                'call_sites': []   
            }
            
            functions[func_id] = func_info
            #func_id_to_info[func_id] = func_info
    
    # Step 2: Build the call relationships
    for item in function_metadata:
        if item.get('category') == 'function' and item.get('callees'):
            # Get the identifier of the calling function
            caller_name = item['name']
            caller_file = item.get('def_file_path', '')
            caller_line = item.get('def_start_line', 0)
            caller_id = f"{caller_name}@{caller_file}:{caller_line}"
            
            # Skip if this function does not exist
            if caller_id not in functions:
                continue
            
            # Process the called functions
            for call_site in item.get('callees', []):
                callee_name = call_site['name']
                callee_file = call_site.get('def_file_path', '')
                callee_line = call_site.get('def_start_line', 0)
                
                callee_id = f"{callee_name}@{callee_file}:{callee_line}"


                call_file = call_site.get('call_file_path', '')
                call_line = call_site.get('call_start_line', 0)
                callsite_id = f"{callee_name}@{call_file}:{call_line}"

                # Create information for an unknown function
                if callee_id not in functions:
                    functions[callee_id] = {
                        'id': callee_id,
                        'name': callee_name,
                        'signature': '',
                        'file_path': callee_file,
                        'is_static': False,
                        'def_start_line': callee_line,
                        'def_end_line': None,
                        'callers': [],
                        'callees': [],
                        'call_sites': [],
                        'is_external': True  # External function flag
                    }
                
                # Update the mapping
                if caller_id not in functions:
                    functions[caller_id] = {}
            
                # Add the call relationship (bidirectional)
                if callee_id not in functions[caller_id]['callees']:
                    functions[caller_id]['callees'].append(callee_id)
                
                if callee_id not in functions[caller_id]['call_sites']:
                    functions[caller_id]['call_sites'].append(callsite_id)

                if caller_id not in functions[callee_id]['callers']:
                    functions[callee_id]['callers'].append(caller_id)

    return functions



def get_main_info(program_dir, database_json, target_cmd, current_path, work_dir, meta_dir, flag=None):

    main_path = database_json[target_cmd]["main_path"]
    main_path = main_path.replace(program_dir, f"{current_path}/{work_dir}")
    meta_data, meta_path = get_metadata(os.path.abspath(main_path), meta_dir, None)

    print(main_path)
    print(meta_path)
    for key, item in meta_data.items():
        if item['name'] == "main":
            line_number = item['start_line']

    target_entry = {
        "target_path" : main_path,
        "target_line" : line_number,
        "target_function" : "main"
    }

    print(target_entry)
    return target_entry


def build_graph(callee_path, callee_main_path):
    """Function that builds a call graph and computes the overall centrality metrics"""
    
    katz_alpha = 0.5
    katz_beta = 1 #100

    data = read_json(callee_path)
    G = nx.DiGraph()
    
    # Add nodes and edges
    related_ids = get_related_data(callee_main_path)
 
    for func_id, func_data in data.items():
        if func_id not in related_ids:
            continue
        
        if len(func_data['callers']) == 0 and len(func_data['callees']) == 0: # added
            continue
        G.add_node(func_id, name=func_data["name"])
        
        # Add edges to callees
        for callee in func_data.get("callees", []):
            G.add_edge(func_id, callee)
    
    # Compute all centrality metrics
    graph_metrics = {}
    
    # 1. Degree-related metrics
    graph_metrics["in_degree"] = dict(G.in_degree())
    graph_metrics["out_degree"] = dict(G.out_degree())
    graph_metrics["degree_centrality"] = nx.degree_centrality(G)
    
    # 1.1 Compute in-degree centrality and out-degree centrality (added)
    node_count = G.number_of_nodes()
    if node_count <= 1:
        graph_metrics["in_degree_centrality"] = {node: 0.0 for node in G.nodes()}
        graph_metrics["out_degree_centrality"] = {node: 0.0 for node in G.nodes()}
    else:
        # Compute in-degree centrality
        graph_metrics["in_degree_centrality"] = {
            node: graph_metrics["in_degree"][node] / (node_count - 1) 
            for node in G.nodes()
        }
        
        # Compute out-degree centrality in the same way (optional)
        graph_metrics["out_degree_centrality"] = {
            node: graph_metrics["out_degree"][node] / (node_count - 1) 
            for node in G.nodes()
        }
    
    # 2. Betweenness centrality (using sampling)
    MAX_NODE_COUNT = 300 # 100
    # Check the number of nodes in the graph and set the k parameter appropriately
    if node_count == 0:
        # Return an empty dictionary if no nodes exist
        graph_metrics["betweenness_centrality"] = {}

    elif node_count < MAX_NODE_COUNT:
        # Use all nodes when the number of nodes is small
        graph_metrics["betweenness_centrality"] = nx.betweenness_centrality(G)
    else:
        # Use sampling when the number of nodes is large
        graph_metrics["betweenness_centrality"] = nx.betweenness_centrality(G, k=MAX_NODE_COUNT)
    
    # 3. PageRank
    graph_metrics["pagerank"] = nx.pagerank(G)
     
    # 4. Eigenvector centrality
    try:
        graph_metrics["eigenvector_centrality"] = nx.eigenvector_centrality_numpy(G)
    except:
        graph_metrics["eigenvector_centrality"] = {node: 0.0 for node in G.nodes()}
    
    # 5. Closeness centrality
    try:
        graph_metrics["closeness_centrality"] = nx.closeness_centrality(G)
    except:
        graph_metrics["closeness_centrality"] = {node: 0.0 for node in G.nodes()}
    
    # 6. Katz centrality
    try:
        # Logic to find an appropriate alpha value
        try:
            # First try with the default values
            graph_metrics["katz_centrality"] = nx.katz_centrality(G, alpha=katz_alpha, beta=katz_beta) #beta=1.0)  #(G, alpha=0.1, beta=1.0)
        except nx.PowerIterationFailedConvergence:
            # If it does not converge, try a smaller alpha value
            # Compute the largest eigenvalue of the adjacency matrix and set an appropriate alpha value
            A = nx.adjacency_matrix(G).todense()
            try:
                eigenvalues = np.linalg.eigvals(A)
                max_eigenvalue = max(abs(eigenvalues))
                # Set an alpha value smaller than the reciprocal of the largest eigenvalue
                safe_alpha = 0.9 / max_eigenvalue if max_eigenvalue > 0 else 0.01
                graph_metrics["katz_centrality"] = nx.katz_centrality(G, alpha=safe_alpha, beta=1.0)
            except:
                # If the eigenvalue computation fails, try a very small alpha value
                graph_metrics["katz_centrality"] = nx.katz_centrality(G, alpha=0.01, beta=1.0)
    except:
        # If it still fails, use the default values
        graph_metrics["katz_centrality"] = {node: 0.0 for node in G.nodes()}
    
    # 7. Compute the combined score (also including in-degree centrality)
    combined_score = {}
    for node in G.nodes():
        score = (
            graph_metrics["in_degree"].get(node, 0) * 1.0 +
            graph_metrics["out_degree"].get(node, 0) * 0.5 +
            graph_metrics["in_degree_centrality"].get(node, 0) * 2.0 +  # Add in-degree centrality
            graph_metrics["betweenness_centrality"].get(node, 0) * 10 +
            graph_metrics["pagerank"].get(node, 0) * 5 +
            graph_metrics["eigenvector_centrality"].get(node, 0) * 3 +
            graph_metrics["closeness_centrality"].get(node, 0) * 2 +
            graph_metrics["katz_centrality"].get(node, 0) * 4
        )
        combined_score[node] = score
    
    graph_metrics["combined_score"] = combined_score
    
    return graph_metrics, G


def build_call_graph(metadata_files: List[List[Dict]]) -> Tuple[Dict[FunctionId, set], Set[FunctionId]]: # Build a call graph from the metadata of multiple files
    #metadata_contents = [read_json(path) for path in metadata_files]  # Load the metadata
    metadata_contents = {}
    for path in metadata_files:
        data = read_json(path)
        if data:
            metadata_contents.update(data)

    #print(metadata_contents)
    graph = defaultdict(set)
    all_functions = {} #set()

    if not any(metadata_contents):
        print("No metadata files found or could not be parsed.")
        return graph, all_functions  # Return default values even on error

    # for file_metadata in metadata_contents:
    #     if file_metadata is None:
    #         continue
    for key, func_data in metadata_contents.items():  # Register the calling function as an identifier
        if func_data['kind'] != "function":
            continue
        call_sites = func_data.get("uses", []) #callees", []) # Record the call relationships
        if func_data["name"] not in all_functions:
            #print(func_data)
            def_file_path, def_start_line, _ = parse_def_loc(func_data['definition'])
            all_functions[f"{func_data["name"]}:::{def_file_path}:::{def_start_line}"] = []

        for call in call_sites:
            if 'kind' not in call:
                continue
            if call['kind'] != "function":
                continue
            call_file_path, call_start_line, _ = parse_def_loc(call['definition'])
            all_functions[f"{func_data["name"]}:::{def_file_path}:::{def_start_line}"].append(f"{call['name']}:::{call_file_path}:::{call_start_line}")

    return graph, all_functions


def topological_cflow_sort(dependencies):
    """Sort functions into topological order using Tarjan's algorithm for strongly connected components, and also detect isolated nodes"""
    def dfs(node, stack, on_stack, visited, component):
        index[node] = len(index)
        low_link[node] = index[node]
        stack.append(node)
        on_stack[node] = True
        visited.add(node)
        
        for neighbor in dependencies.get(node, []):
            if neighbor not in visited:
                dfs(neighbor, stack, on_stack, visited, component)
                low_link[node] = min(low_link[node], low_link[neighbor])
            elif on_stack[neighbor]:
                low_link[node] = min(low_link[node], index[neighbor])
        
        if low_link[node] == index[node]:
            scc = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                scc.append(w)
                if w == node:
                    break
            component.append(scc)

    index = {}
    low_link = {}
    on_stack = defaultdict(bool)
    visited = set()
    stack = []
    component = []

    # Collect all nodes (including nodes at both ends of the dependencies)
    all_nodes = set(dependencies.keys())
    for deps in dependencies.values():
        all_nodes.update(deps)
    
    # Detect isolated nodes
    isolated_nodes = {
        node for node in all_nodes 
        if (node not in dependencies or not dependencies.get(node)) and
           all(node not in deps for deps in dependencies.values())
    }

    # Run DFS on each node to find the strongly connected components
    for node in dependencies:
        if node not in visited:
            dfs(node, stack, on_stack, visited, component)

    topo_sort = [] # Expand the nodes of each strongly connected component into a list to obtain the topological order
    for scc in component:
        if len(scc) > 1: # Processing to control the order within a strongly connected component
            scc_sorted = sorted(scc, key=lambda x: index[x]) # When a cycle is detected, reorder appropriately to order each node
            topo_sort.extend(scc_sorted)
        else:
            topo_sort.extend(scc)

    return topo_sort, isolated_nodes



def analyze_call_dependencies(target_dir, meta_dir, database_dir, is_program_path, reformed_path, isolated_path) -> Dict: 
    print("analyze_call_dependencies...")

    metadata_files = []
    target_paths = []
    parent_paths = []
    program_files = set(read_json(is_program_path))
    print(program_files)

    for root, _, files in os.walk(target_dir):
        for file in files:
            if file.endswith('.c') or file.endswith('.h'):
                if file.endswith('.c'):
                    suffix = "_c"
                elif file.endswith('.h'):
                    suffix = "_h"
                file_path = os.path.join(root, file)
                print(file_path)
                meta_path = get_metadata(file_path, meta_dir, True) #meta_dir + "/" + file_path[:-2] + suffix + ".json"

                abs_path = os.path.abspath(file_path)
                if abs_path in program_files:
                    metadata_files.append(meta_path)

                target_paths.append(file_path)


    graph, all_functions = build_call_graph(metadata_files) 

    cflow_sorted_functions, isolated_nodes = topological_cflow_sort(all_functions)

    write_json(f"{database_dir}/functions_all.json", all_functions)
    write_json(f"{database_dir}/functions_graph.json", list(graph))

    #cflow_sorted_functions = topological_cflow_sort(graph)
    write_json(f"{database_dir}/functions_cflow.json", cflow_sorted_functions)
    print(isolated_nodes)

    reformed_functions = []
    for def_string in cflow_sorted_functions:
        print(def_string)
        name, def_file_path, def_start_line = parse_function_data(def_string)
        reformed_functions.append({
            "name" : name,
            "def_file_path" : def_file_path,
            "def_start_line" : def_start_line,
        })

    
    print("\nTopologically sorted functions:") 
    i = 0
    for func in reformed_functions:
        func_name = func['name'] 
        file_path = func['def_file_path']
        start_line = func['def_start_line']

        print(f"\n{i}. {func_name}")
        print(f"   Defined in: {file_path}")

        """
        calls = result["dependencies"][func]
        if calls:
            print("   Calls:")
            for callee in calls:
                print(f"    - {callee.name} (in {callee.file_path})")
        """

    write_json(reformed_path, reformed_functions)
    write_json(isolated_path, list(isolated_nodes))

    return reformed_functions, isolated_nodes  



def get_jsonfiles(directory):
    """
    Function that recursively searches for all JSON files in a directory and returns a list of their paths
    
    Parameters:
    directory (str): The path of the directory to search
    
    Returns:
    list: A list of absolute paths of the JSON files found
    """
    json_files = []
    
    # Check whether the directory exists
    if not os.path.isdir(directory):
        print(f"Error: {directory} is not a valid directory")
        return json_files
    
    # Traverse the directory recursively
    for root, dirs, files in os.walk(directory):
        for file in files:
            # Add files with a .json extension to the list
            if file.lower().endswith('.json'):
                json_files.append(os.path.join(root, file))
    
    return json_files


def write_metrics(target_cmd, graph_metrics):
    meta_paths = get_jsonfiles(f"metadata_{target_cmd}")
    for meta_path in meta_paths:
        meta_data = read_json(meta_path)
        for key, item in meta_data.items():
            #item['pagerank'] = get_pagerank(item, graph_metrics)
            result = get_metrics(item, graph_metrics)
            for key, values in result.items():
                item[key] = result[key]
    
        write_json(meta_path, meta_data)


def calculate_gini(values):
    """Compute the Gini coefficient"""
    if len(values) == 0:
        return np.nan
    
    sorted_values = np.sort(values)
    n = len(values)
    index = np.arange(1, n + 1)
    gini = (2 * np.sum(index * sorted_values)) / (n * np.sum(sorted_values)) - (n + 1) / n
    return gini


def analyze_graph_structures(graph_data_dict):
    
    results = []
    
    for target_cmd, (graph_metrics, G) in graph_data_dict.items():
        print(f"Analyzing {target_cmd}...")
        
        stats = {"target_cmd": target_cmd}
        
        # === 1. Basic graph statistics ===
        stats["num_nodes"] = G.number_of_nodes()
        stats["num_edges"] = G.number_of_edges()
        
        if stats["num_nodes"] > 0:
            stats["avg_in_degree"] = np.mean([d for n, d in G.in_degree()])
            stats["avg_out_degree"] = np.mean([d for n, d in G.out_degree()])
            stats["density"] = nx.density(G)
        else:
            stats["avg_in_degree"] = 0
            stats["avg_out_degree"] = 0
            stats["density"] = 0
        
        # === 2. Structural features of the graph ===
        # Strongly connected component analysis
        sccs = list(nx.strongly_connected_components(G))
        stats["num_strongly_connected"] = len(sccs)
        stats["largest_scc_size"] = len(max(sccs, key=len)) if sccs else 0
        stats["largest_scc_ratio"] = stats["largest_scc_size"] / stats["num_nodes"] if stats["num_nodes"] > 0 else 0
        
        # Weakly connected component analysis
        wccs = list(nx.weakly_connected_components(G))
        stats["num_weakly_connected"] = len(wccs)
        stats["largest_wcc_size"] = len(max(wccs, key=len)) if wccs else 0
        
        # Diameter and average shortest path length (computed on the largest WCC)
        if stats["largest_wcc_size"] > 1:
            largest_wcc = max(wccs, key=len)
            subgraph = G.subgraph(largest_wcc)
            
            try:
                # Treat as an undirected graph for the computation
                undirected = subgraph.to_undirected()
                stats["diameter"] = nx.diameter(undirected)
                stats["avg_shortest_path"] = nx.average_shortest_path_length(undirected)
            except:
                stats["diameter"] = np.nan
                stats["avg_shortest_path"] = np.nan
            
            try:
                stats["clustering_coefficient"] = nx.average_clustering(undirected)
            except:
                stats["clustering_coefficient"] = np.nan
        else:
            stats["diameter"] = np.nan
            stats["avg_shortest_path"] = np.nan
            stats["clustering_coefficient"] = np.nan
        
        # === 3. Distribution characteristics of centrality metrics ===
        centrality_metrics = [
            "in_degree_centrality",
            "out_degree_centrality", 
            "betweenness_centrality",
            "pagerank",
            "closeness_centrality"
        ]
        
        for metric in centrality_metrics:
            if metric in graph_metrics and graph_metrics[metric]:
                values = np.array(list(graph_metrics[metric].values()))
                
                # Skewness
                stats[f"{metric}_skew"] = skew(values) if len(values) > 0 else np.nan
                
                # Gini coefficient
                stats[f"{metric}_gini"] = calculate_gini(values)
                
                # Top 10% concentration
                if len(values) > 0:
                    top_10_percent = int(np.ceil(len(values) * 0.1))
                    sorted_values = np.sort(values)[::-1]
                    top_sum = np.sum(sorted_values[:top_10_percent])
                    total_sum = np.sum(values)
                    stats[f"{metric}_top10_concentration"] = top_sum / total_sum if total_sum > 0 else 0
                else:
                    stats[f"{metric}_top10_concentration"] = np.nan
        
        results.append(stats)
    
    # Convert to a DataFrame
    df = pd.DataFrame(results)
    
    # Organize the column order
    basic_cols = ["target_cmd", "num_nodes", "num_edges", "avg_in_degree", 
                  "avg_out_degree", "density"]
    structure_cols = ["num_strongly_connected", "largest_scc_size", "largest_scc_ratio",
                     "num_weakly_connected", "largest_wcc_size", 
                     "diameter", "avg_shortest_path", "clustering_coefficient"]
    
    # Collect centrality-related columns
    centrality_cols = [col for col in df.columns if col not in basic_cols + structure_cols]
    
    # Reorder the columns
    ordered_cols = basic_cols + structure_cols + sorted(centrality_cols)
    df = df[ordered_cols]
    
    return df


def estimate_cent_from_graph(structure_dict, rules, default_method="random_t"):
    """
    Estimate the optimal centrality strategy from graph structural features.

    Uses the thresholds and weights stored in rules["feature_thresholds"]
    (loaded from hr_decision_rules.json). The scoring logic is identical to
    the one used inside recommend_methods_for_programs.
    """
    scores = {}
    matched_conditions = {}

    for method, thresholds in rules.get("feature_thresholds", {}).items():
        if not thresholds:
            scores[method] = 0.0
            matched_conditions[method] = []
            continue

        matched_weight = 0.0
        total_weight = 0.0
        conditions = []

        for feature, info in thresholds.items():
            if feature not in structure_dict:
                continue

            value = structure_dict[feature]
            operator = info["operator"]
            threshold = info["value"]
            weight = abs(info["correlation"])  # correlation strength as weight

            total_weight += weight

            is_matched = (
                (operator == ">=" and value >= threshold) or
                (operator == "<=" and value <= threshold)
            )
            if is_matched:
                matched_weight += weight
                conditions.append(info["interpretation"])

        # weighted match ratio
        scores[method] = matched_weight / total_weight if total_weight > 0 else 0.0
        matched_conditions[method] = conditions

    # no method matched any condition -> fall back to baseline
    if not scores or all(s == 0 for s in scores.values()):
        return default_method, 0.0, scores, matched_conditions

    recommended_method, confidence = max(scores.items(), key=lambda x: x[1])
    return recommended_method, confidence, scores, matched_conditions


def get_estimated_cent(
    target_cmd, paths, default_method="random_t"
):
    """
    Estimate the optimal centrality strategy directly from build_graph output.

    Converts (graph_metrics, G) into structural features via
    analyze_graph_structures, then delegates to estimate_cent_from_graph.
    """
    # Load decisions
    decision = {}
    if os.path.exists(paths.decision_path):
        decision = read_json(paths.decision_path)
        if decision is not None:
            if target_cmd in decision:
                print(f"Method: {decision[target_cmd]}")
                return decision[target_cmd]
        else:
            decision = {}

    # Load decision rules and build the call graph
    rules = read_json(paths.decision_rule_path)

    graph_metrics, G = build_graph(paths.callee_path, paths.callee_main_path)

    # analyze_graph_structures expects {target_cmd: (graph_metrics, G)}
    df = analyze_graph_structures({target_cmd: (graph_metrics, G)})
    structure_dict = df.iloc[0].drop("target_cmd").to_dict()

    recommended_method, confidence, scores, matched_conditions = estimate_cent_from_graph(
        structure_dict, rules, default_method
    )

    decision[target_cmd] = recommended_method
    write_json(paths.decision_path, decision)

    print(f"Recommended method: {recommended_method}")
    return recommended_method


