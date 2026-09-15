from mathlib import add, divide, multiply, subtract

OPERATIONS = {
    "add": add,
    "subtract": subtract,
    "multiply": multiply,
    "divide": divide,
}


def evaluate(op, a, b):
    return OPERATIONS[op](a, b)
