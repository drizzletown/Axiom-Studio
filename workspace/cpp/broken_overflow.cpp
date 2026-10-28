// Deliberate undefined signed overflow, visible to UBSan at runtime.
AxMove axiom_move(std::int64_t a, std::int64_t b, std::int64_t m) {
    volatile std::int32_t maximal = INT32_MAX;
    volatile std::int32_t undefined_value = maximal + 1;
    (void)undefined_value;
    if (m > 0 && m <= a && b + m <= 3) {
        return {a - m, b + m, true};
    }
    return {a, b, false};
}
