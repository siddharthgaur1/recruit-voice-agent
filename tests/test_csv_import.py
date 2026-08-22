from src.db.repo import import_leads_csv, make_engine, make_session_factory


def test_import_leads_csv(tmp_path):
    csv_path = tmp_path / "leads.csv"
    csv_path.write_text(
        "phone,name,dnc_flag\n"
        "+911111111111,Asha,\n"
        "+912222222222,Ravi,true\n"
        "+913333333333,,\n",
        encoding="utf-8",
    )

    engine = make_engine(str(tmp_path / "leads.db"))
    session = make_session_factory(engine)()
    leads = import_leads_csv(session, csv_path)

    assert len(leads) == 3
    assert leads[0].phone == "+911111111111"
    assert leads[0].name == "Asha"
    assert leads[0].dnc_flag is False
    assert leads[0].status == "QUEUED"
    assert leads[1].dnc_flag is True
    assert leads[2].name is None
    session.close()
