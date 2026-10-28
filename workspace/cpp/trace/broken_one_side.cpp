static bool source_state=false,mirror_state=false;
extern "C" void axiom_reset(int left,int right) {
    source_state=left!=0;mirror_state=right!=0;
}
extern "C" int axiom_step(int opcode,int desired,int* left,int* right) {
    bool result=false;
    switch(opcode) {
    case 0: source_state=(desired!=0); result=true; break; // BUG: mirror never updated
    case 1: result=source_state;break;
    case 2: result=mirror_state;break;
    default: return -1;
    }
    *left=static_cast<int>(source_state);*right=static_cast<int>(mirror_state);
    return static_cast<int>(result);
}
