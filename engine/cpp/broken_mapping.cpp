// Deliberate error: deposits into the wrong balance.
AxMove axiom_move(std::int64_t a, std::int64_t b, std::int64_t m) {
    if (m > 0 && m <= a && b + m <= 3) {
        return {a - m, b, true};
    }
    return {a, b, false};
}
