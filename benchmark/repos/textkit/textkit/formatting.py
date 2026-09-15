def title_case(text):
    return " ".join(word.capitalize() for word in text.split())


def truncate(text, limit):
    return text[:limit] + "..."
