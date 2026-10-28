// Pure transition for finite TwoAccount model; AX-HLD-1.0 P1.
AxMove axiom_move(std::int64_t a, std::int64_t b, std::int64_t m) {
    if (m > 0 && m <= a && b + m <= 3) {
        return {a - m, b + m, true};
    }
    return {a, b, false};
}
