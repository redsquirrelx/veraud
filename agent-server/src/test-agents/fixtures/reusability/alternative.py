from policy import PricePolicy


def configured_policy(backend):
    policy = PricePolicy()
    policy.client = backend
    return policy
