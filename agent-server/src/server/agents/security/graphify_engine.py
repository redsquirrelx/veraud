import ast
import json
import os


class GraphifyEngine:
    """Motor para transformar código fuente en un Grafo de Dependencias y AST

    (Code Property Graph) para uso de los agentes de seguridad.
    """

    def __init__(self):
        self.nodes = []
        self.edges = []

    def build_graph_from_directory(self, target_path: str) -> dict:
        for root, _, files in os.walk(target_path):
            for file in files:
                if file.endswith(".py"):
                    full_path = os.path.join(root, file)
                    self._parse_file(full_path, file)

        graph_data = {
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
            "nodes": self.nodes,
            "edges": self.edges,
        }
        return graph_data

    def _parse_file(self, full_path: str, file_name: str):
        self.nodes.append(
            {"id": file_name, "type": "FILE", "label": file_name}
        )
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=file_name)

            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    func_id = f"{file_name}::{node.name}"
                    self.nodes.append(
                        {
                            "id": func_id,
                            "type": "FUNCTION",
                            "label": node.name,
                            "line": node.lineno,
                        }
                    )
                    self.edges.append(
                        {
                            "source": file_name,
                            "target": func_id,
                            "relation": "CONTAINS_FUNCTION",
                        }
                    )
                elif isinstance(node, ast.Import) or isinstance(
                    node, ast.ImportFrom
                ):
                    for alias in node.names:
                        self.edges.append(
                            {
                                "source": file_name,
                                "target": alias.name,
                                "relation": "IMPORTS_MODULE",
                            }
                        )
        except Exception as e:
            pass


if __name__ == "__main__":
    engine = GraphifyEngine()
    result = engine.build_graph_from_directory("samples")
    print(
        f"[+] Graphify completado: {result['total_nodes']} nodos, {result['total_edges']} aristas generadas."
    )
    with open("graph_analysis.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=4)
