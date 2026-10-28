// Deliberate error: wrongly rejects a transfer of all remaining funds.
AxMove axiom_move(std::int64_t a, std::int64_t b, std::int64_t m) {
    if (m > 0 && m < a && b + m <= 3) {
        return {a - m, b + m, true};
    }
    return {a, b, false};
}
