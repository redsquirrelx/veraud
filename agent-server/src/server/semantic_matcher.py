from sentence_transformers import SentenceTransformer, util


MODEL_NAME = "all-MiniLM-L6-v2"

model = SentenceTransformer(MODEL_NAME)


def find_best_match(requirement: str, code_fragments: list[str]) -> dict:
    """
    Compara un requisito funcional contra una lista de fragmentos
    de código y devuelve el fragmento con mayor similitud semántica.
    """

    requirement_embedding = model.encode(
        requirement,
        convert_to_tensor=True
    )

    code_embeddings = model.encode(
        code_fragments,
        convert_to_tensor=True
    )

    similarities = util.cos_sim(
        requirement_embedding,
        code_embeddings
    )[0]

    best_index = int(similarities.argmax())
    best_score = float(similarities[best_index])

    return {
        "requirement": requirement,
        "best_match": code_fragments[best_index],
        "similarity": best_score,
    }
