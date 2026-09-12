"""One module per row of the wiring table, named for the method it calls.

    decide.py    schedule clock: StrategyModel.decide
    compute.py   schedule clock: DataModel.compute
    accrue.py    market clock, 1st: a place (design §7.3)
    execute.py   market clock, 2nd: the pending intent fills, the account appends
    value.py     market clock, 3rd: the framework marks the committed book
    observe.py   market clock, 4th: the declared Compliance rules observe it
"""
