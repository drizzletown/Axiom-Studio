// Deliberate hidden state: incorrectly accepts the first request only.
AxMove axiom_move(std::int64_t a, std::int64_t b, std::int64_t m) {
    static bool first = true;
    if (first && m > 0 && m <= a && b + m <= 3) {
        first = false;
        return {a-m,b+m,true};
    }
    return {a,b,false};
}
