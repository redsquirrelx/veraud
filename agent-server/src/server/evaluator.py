import json
from pathlib import Path

from server.semantic_matcher import find_best_match


DATASET_PATH = Path(__file__).resolve().parents[3] / "datasets" / "functional_requirements.json"


def evaluate_dataset() -> dict:
    with open(DATASET_PATH, "r", encoding="utf-8") as file:
        dataset = json.load(file)

    results = []
    correct = 0
    total = len(dataset)

    for item in dataset:
        requirement_id = item["requirement_id"]
        requirement = item["requirement"]

        candidates = item["candidates"]

        code_fragments = [candidate["code"] for candidate in candidates]

        best_match = find_best_match(
            requirement,
            code_fragments
        )

        best_code = best_match["best_match"]

        expected_candidates = [
            candidate
            for candidate in candidates
            if candidate["correcto"] is True
        ]

        is_correct = any(
            candidate["code"] == best_code
            for candidate in expected_candidates
        )

        if is_correct:
            correct += 1

        results.append({
            "requirement_id": requirement_id,
            "correct": is_correct,
            "similarity": best_match["similarity"],
        })

    accuracy = (correct / total) * 100 if total > 0 else 0

    return {
        "total": total,
        "correct": correct,
        "incorrect": total - correct,
        "accuracy": accuracy,
        "results": results,
    }


if __name__ == "__main__":
    evaluation = evaluate_dataset()

    print("\n=== EVALUACIÓN EN-021 ===")
    print(f"Total de requisitos: {evaluation['total']}")
    print(f"Aciertos: {evaluation['correct']}")
    print(f"Errores: {evaluation['incorrect']}")
    print(f"Precisión: {evaluation['accuracy']:.2f}%")

    print("\nResultados individuales:")

    for result in evaluation["results"]:
        status = "CORRECTO" if result["correct"] else "INCORRECTO"

        print(
            f"{result['requirement_id']}: "
            f"{status} - "
            f"similitud={result['similarity']:.4f}"
        )
