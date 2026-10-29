#include "ledger.hpp"
#include "format.hpp"
#include <iostream>
int main() {
    Ledger l;
    if(!l.move(1)) return 1;
    if(receipt(l.from,l.to)!="2:1") return 2;
    if(!l.move(2)) return 3;
    if(receipt(l.from,l.to)!="0:3" || l.move(1)) return 4;
    std::cout << "PASS integration\n";
}
