class CLIArgs:
    def __init__(
            self, debug: bool = False, verbose: bool = False,
            measure: bool = True, clean: bool = False,
            clean_all: bool = False, short_cut: bool = False,
            analyze: bool = False, provenance: bool = True):
        self.debug = debug
        self.verbose = verbose
        self.measure = measure
        self.clean = clean
        self.clean_all = clean_all
        self.short_cut = short_cut
        self.analyze = analyze
        self.provenance = provenance
