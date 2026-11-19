import logging

logger = logging.getLogger(__name__)

def evict(cache, key):
    cache.pop(key, None)
    logger.info("Deleted from cache: " + key)
