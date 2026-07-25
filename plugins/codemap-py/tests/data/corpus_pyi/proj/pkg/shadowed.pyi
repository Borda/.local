# Scenario: sibling module shadowed by an authoritative shadowed.py.
# Expected: reported as shadowed_stub; declarations here MUST NOT replace or
# duplicate the pkg.shadowed module built from shadowed.py, and the private
# _double helper (absent from this stub) must remain in the index.
def impl(value: int) -> int: ...
