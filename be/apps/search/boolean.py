"""Boolean query parser. AND/OR/NOT, phrases, parentheses. Never produces SQL text."""

from __future__ import annotations

from dataclasses import dataclass

from django.contrib.postgres.search import SearchQuery

MAX_QUERY_LENGTH = 2000


class BooleanSyntaxError(ValueError):
    def __init__(self, message: str, position: int = 0):
        super().__init__(message)
        self.position = position


@dataclass
class Node:
    kind: str
    value: str | None = None
    left: "Node | None" = None
    right: "Node | None" = None


class BooleanParser:
    def __init__(self, text: str):
        self.text = text
        self.n = len(text)
        self.i = 0

    def parse(self) -> Node:
        if self.n > MAX_QUERY_LENGTH:
            raise BooleanSyntaxError(f"Query is longer than {MAX_QUERY_LENGTH} characters.", 0)
        self._skip()
        if self.i >= self.n:
            raise BooleanSyntaxError("Enter a search query.", 0)
        node = self._parse_or()
        self._skip()
        if self.i < self.n:
            raise BooleanSyntaxError("Unexpected text in the query.", self.i)
        return node

    def _parse_or(self) -> Node:
        left = self._parse_and()
        while True:
            self._skip()
            if not self._match_kw("OR"):
                return left
            right = self._parse_and()
            left = Node("or", left=left, right=right)

    def _parse_and(self) -> Node:
        left = self._parse_not()
        while True:
            self._skip()
            if self.i >= self.n or self._peek_kw("OR") or self.text[self.i] == ")":
                return left
            if self._match_kw("AND"):
                right = self._parse_not()
                left = Node("and", left=left, right=right)
                continue
            if self._starts_primary():
                right = self._parse_not()
                left = Node("and", left=left, right=right)
                continue
            return left

    def _parse_not(self) -> Node:
        self._skip()
        if self._match_kw("NOT"):
            child = self._parse_not()
            return Node("not", left=child)
        return self._parse_primary()

    def _parse_primary(self) -> Node:
        self._skip()
        if self.i >= self.n:
            raise BooleanSyntaxError("Expected a term.", self.i)
        if self.text[self.i] == "(":
            self.i += 1
            node = self._parse_or()
            self._skip()
            if self.i >= self.n or self.text[self.i] != ")":
                raise BooleanSyntaxError("Missing closing parenthesis.", self.i)
            self.i += 1
            return node
        if self.text[self.i] == '"':
            self.i += 1
            start = self.i
            while self.i < self.n and self.text[self.i] != '"':
                self.i += 1
            if self.i >= self.n:
                raise BooleanSyntaxError("Missing closing quote.", start)
            phrase = self.text[start : self.i].strip()
            self.i += 1
            if not phrase:
                raise BooleanSyntaxError("Empty phrase.", start)
            return Node("phrase", value=phrase)
        start = self.i
        while self.i < self.n and self.text[self.i] not in " \t\r\n()":
            self.i += 1
        term = self.text[start : self.i]
        if not term or term.upper() in {"AND", "OR", "NOT"}:
            raise BooleanSyntaxError("Expected a term.", start)
        return Node("term", value=term)

    def _starts_primary(self) -> bool:
        if self.i >= self.n:
            return False
        char = self.text[self.i]
        if char in {"(", '"'}:
            return True
        if self._peek_kw("AND") or self._peek_kw("OR"):
            return False
        return char.isalnum() or char in {"+", "#", ".", "_", "-"}

    def _match_kw(self, word: str) -> bool:
        self._skip()
        end = self.i + len(word)
        if self.text[self.i : end].upper() != word:
            return False
        if end < self.n and (self.text[end].isalnum() or self.text[end] == "_"):
            return False
        self.i = end
        return True

    def _peek_kw(self, word: str) -> bool:
        saved = self.i
        matched = self._match_kw(word)
        self.i = saved
        return matched

    def _skip(self) -> None:
        while self.i < self.n and self.text[self.i].isspace():
            self.i += 1


def parse_boolean(text: str) -> Node:
    return BooleanParser(text or "").parse()


def to_search_query(node: Node, *, config: str = "english") -> SearchQuery:
    if node.kind == "term":
        return SearchQuery(node.value, search_type="plain", config=config)
    if node.kind == "phrase":
        return SearchQuery(node.value, search_type="phrase", config=config)
    if node.kind == "and":
        return to_search_query(node.left, config=config) & to_search_query(node.right, config=config)
    if node.kind == "or":
        return to_search_query(node.left, config=config) | to_search_query(node.right, config=config)
    if node.kind == "not":
        return ~to_search_query(node.left, config=config)
    raise BooleanSyntaxError("Unknown query node.")


def node_to_dict(node: Node) -> dict:
    return {
        "kind": node.kind,
        "value": node.value,
        "left": node_to_dict(node.left) if node.left else None,
        "right": node_to_dict(node.right) if node.right else None,
    }
