"""Whole-contract scale-out planning; broker partial execution is not enabled."""


def partial_plan(ladder, original_quantity, remaining, reached_r, completed):
    if type(original_quantity) is not int or type(remaining) is not int or not 0 <= remaining <= original_quantity <= 4:
        raise ValueError("Invalid whole-contract position quantity")
    if original_quantity == 1 or remaining <= 1:
        return None
    for index, (milestone, quantity) in enumerate(ladder):
        if index not in completed and reached_r >= milestone:
            # An explicit ladder is never silently resized to fit a smaller fill.
            if quantity >= remaining:
                return dict(index=index, blocked=True, reason="Configured partial would leave no whole-contract remainder")
            return dict(index=index, quantity=quantity, milestone=milestone, blocked=False)
    return None
