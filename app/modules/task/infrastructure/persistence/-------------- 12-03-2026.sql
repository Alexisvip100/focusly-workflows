-------------- 12-03-2026
-- Fact_AR_Facturas_Cobros -- ADAPTACION 1:1 de
-- "REPORTES ORIGINALES/QUERY_FACTURAS_COBRADAS_Y_PENDIENTES_RIVI_AR.sql" para ejecutar en
-- cat_ocloud_dv. Cambio de catalogo cat_ocloud_pr -> cat_ocloud_dv (mecanico) salvo donde se anota
-- lo contrario.
--
-- >>> FACT: sustitucion real -- CLTRX_LOOKUP / IMPRESA_LOOKUP (fnd_lookup_values_tl, Language='E')
-- se reemplazan por dim_lookup_nueva (cat_fnd_lookup.sql), misma tabla fuente, sin fan-out
-- (validado en vivo, sesion 2026-09-14, ver Fact_Inv_Receiving_Transaction.sql).
--
-- >>> FACT: NO se sustituyen las 8 ocurrencias de crm_ffbu_businessunitpvo (subquery repetida que
-- resuelve BUSINESSUNITID via LEGALENTITYLEGALEMPLOYERFLAG='Y' + LEGALENTITYNAME) por
-- cat_gl_business_unit.sql: ese catalogo NO expone LegalEntityLegalEmployerFlag, columna
-- indispensable para el filtro -- sin ella no se puede replicar el mismo resultado.
--
-- >>> FACT: CORRECCION 2026-09-15 -- SAWITH3+SAWITH4 (crm_crm_hz_customeraccountextractpvo +
-- hz_parties, resuelven PARTY_NAME/ACCOUNTNAME/RUT) SI se sustituyen, por cat_hz_customer_account.sql
-- (dimensiones/comunes/), NO por cat_hz_customer_version2.sql (NUEVAS_DIMENSIONES/) que se sigue
-- descartando: ese catalogo resuelve PartyName desde crm_crm_hz_partyextractpvo (PVO), no desde
-- hz_parties (tabla base) como el reporte original. cat_hz_customer_account.sql si usa hz_parties
-- directo (misma fuente), validado en vivo -- ver detalle junto a la definicion de SAWITH3/SAWITH4
-- mas abajo.
--
-- Grano identico al de QUERY_FACTURAS_COBRADAS_Y_PENDIENTES_RIVI_AR.sql -- ningun calculo de
-- negocio ni join se modifico salvo la sustitucion de lookup anotada arriba.

WITH
COBROS_IMP as (

select 
CASE WHEN GCC.CodeCombinationSegment4 IN ('21110017', '21110029') THEN 'IEPS' ELSE 'IVA' END TIPO_IMPTO
,ARAA.ArReceivableApplicationAppliedCustomerTrxId
,GCC.CodeCombinationSegment4 || '.' || GCC.CodeCombinationSegment5 || '.' ||  GCC.CodeCombinationSegment6 COMB_CONT_COBRO
,gcc.CodeCombinationSegment6  -------------------!!!!!!!!!!!!!!!
from cat_ocloud_dv.rg1glofsn_cz.fscm_fin_ar_receivableapplicationextractpvo ARAA
inner join cat_ocloud_dv.rg1glofsn_cz.fscm_fin_xla_subledgerjournaleventextractpvo xe
on ARAA.ArReceivableApplicationEventId=xe.EventPEOEventId
AND ARAA.ArReceivableApplicationStatus = 'APP'
inner join cat_ocloud_dv.rg1glofsn_cz.fscm_fin_xla_subledgerjournaltransactionentityextractpvo XTE
ON XTE.TransactionEntityId=XE.EventPEOEntityId
AND XTE.TransactionEntityCode = 'RECEIPTS'
INNER JOIN cat_ocloud_dv.rg1glofsn_cz.vw_xla_ae_headers XAH
ON ARAA.ArReceivableApplicationEventId=XAH.EVENT_ID
AND XTE.TransactionEntityId=XAH.ENTITY_ID
INNER JOIN cat_ocloud_dv.rg1glofsn_cz.fscm_fin_xla_subledgerjournallineextractpvo xal
ON XAH.AE_HEADER_ID=XAL.JournalEntryLineAeHeaderId
AND XAL.JournalEntryLineAccountingClassCode='TAX'
INNER JOIN cat_ocloud_dv.rg1glofsn_cz.fscm_fin_gl_codecombinationextractpvo GCC
ON XAL.JournalEntryLineCodeCombinationId=GCC.CodeCombinationCodeCombinationId
AND GCC.CodeCombinationSegment4 IN ('21110017', '21110029','21110003', '21110004')
WHERE   1 = 1           

/*Parametro de Entidad--test_new_filter_time*/
AND ARAA.ArReceivableApplicationOrgId = (select T1000008.BUSINESSUNITID
                            from 
                                 cat_ocloud_dv.rg1glofsn_cz.crm_ffbu_businessunitpvo T1000008
                            INNER JOIN cat_ocloud_dv.rg1glofsn_cz.fscm_fin_xle_legalentityextractpvo T1000011
                            ON T1000008.LEGALENTITYLEGALENTITYIDENTIFIER=T1000011.LEGALENTITYLEGALENTITYIDENTIFIER
                            WHERE T1000011.LEGALENTITYLEGALEMPLOYERFLAG = 'Y'
                            AND UPPER(T1000011.LEGALENTITYNAME) = upper({p_entidad_legal})
                            GROUP BY T1000008.BUSINESSUNITID
                            )

GROUP BY
CASE WHEN GCC.CodeCombinationSegment4 IN ('21110017', '21110029') THEN 'IEPS' ELSE 'IVA' END 
,ARAA.ArReceivableApplicationAppliedCustomerTrxId
,GCC.CodeCombinationSegment4 || '.' || GCC.CodeCombinationSegment5 || '.' ||  GCC.CodeCombinationSegment6 
,gcc.CodeCombinationSegment6  -------------------!!!!!!!!!!!!!!!


)
,
CMFACT AS (
  SELECT * 
  from (SELECT  ROW_NUMBER() OVER (PARTITION BY ARRECEIVABLEAPPLICATIONCUSTOMERTRXID order by ARRECEIVABLEAPPLICATIONCUSTOMERTRXID) as row_num, 
                rec.ARRECEIVABLEAPPLICATIONCUSTOMERTRXID, ra.RACUSTOMERTRXTRXNUMBER, 
                'Factura' ESTATUS, 
                rec.ARRECEIVABLEAPPLICATIONAPPLYDATE,
                rec.ARRECEIVABLEAPPLICATIONAMOUNTAPPLIED
        FROM    cat_ocloud_dv.rg1glofsn_cz.fscm_fin_ar_receivableapplicationextractpvo rec
        left join cat_ocloud_dv.rg1glofsn_cz.fscm_fin_ar_transactionheaderextractpvo ra
            ON ra.RACUSTOMERTRXCUSTOMERTRXID = rec.ARRECEIVABLEAPPLICATIONAPPLIEDCUSTOMERTRXID
            AND rec.ARRECEIVABLEAPPLICATIONSTATUS = 'APP'
            AND rec.ARRECEIVABLEAPPLICATIONDISPLAY = 'Y'
        WHERE   1 = 1
          
            /*PARAMS*/
            AND RA.RACUSTOMERTRXORGID = (select  T1000008.BUSINESSUNITID
                            from 
                                 cat_ocloud_dv.rg1glofsn_cz.crm_ffbu_businessunitpvo T1000008
                            INNER JOIN cat_ocloud_dv.rg1glofsn_cz.fscm_fin_xle_legalentityextractpvo T1000011
                            ON T1000008.LEGALENTITYLEGALENTITYIDENTIFIER=T1000011.LEGALENTITYLEGALENTITYIDENTIFIER
                            WHERE T1000011.LEGALENTITYLEGALEMPLOYERFLAG = 'Y'
                            AND UPPER(T1000011.LEGALENTITYNAME) = upper({p_entidad_legal})
                            GROUP BY T1000008.BUSINESSUNITID
                            )
            /*PERIODO DE PAGO--test_new_filter_time*/
            AND ((DECODE(date_format({p_periodo_pago_from},'yyyy-MM-dd HH24:mm:SS'),NULL,date_format('1900-01-01 00:00:00','yyyy-MM-dd HH24:mm:SS')
                ,date_format( rec.ARRECEIVABLEAPPLICATIONAPPLYDATE,'yyyy-MM-dd HH24:mm:SS'))
                between NVL(date_format({p_periodo_pago_from}, 'yyyy-MM-dd HH24:mm:SS'),date_format('1900-01-01 00:00:00','yyyy-MM-dd HH24:mm:SS')) 
                and NVL(date_format({p_periodo_pago_to}, 'yyyy-MM-dd HH24:mm:SS'),date_format('1900-01-01 00:00:00','yyyy-MM-dd HH24:mm:SS'))
                ) OR  rec.ARRECEIVABLEAPPLICATIONAPPLYDATE IS NULL)
       )
  WHERE row_num = 1

),


ar_payment_schedule AS (
  SELECT  arps.arpaymentschedulecustomertrxid, 
          arps.arpaymentschedulegldate, 
          case arps.arpaymentschedulestatus when 'VD' then arps.arpaymentschedulestatus else ' ' end arpaymentschedulestatus, 
          sum(arps.arpaymentscheduleamountadjusted) arpaymentscheduleamountadjusted, 
          sum(arps.arpaymentscheduleamountcredited) arpaymentscheduleamountcredited,
          sum(arps.arpaymentscheduleamountindispute) arpaymentscheduleamountindispute, 
          sum(arps.arpaymentscheduleamountlineitemsoriginal) arpaymentscheduleamountlineitemsoriginal, 
          sum(arps.arpaymentscheduleamountdueoriginal) arpaymentscheduleamountdueoriginal, 
          sum(arps.arpaymentscheduleamountdueremaining) arpaymentscheduleamountdueremaining
  FROM    cat_ocloud_dv.rg1glofsn_cz.fscm_fin_ar_paymentscheduleextractpvo arps
  WHERE   1=1
    
      and arps.arpaymentscheduleamountdueoriginal != 0
      /*Parametro de Entidad--test_new_filter_time*/
      and arps.arpaymentscheduleorgid = (select  T1000008.BUSINESSUNITID
                            from cat_ocloud_dv.rg1glofsn_cz.crm_ffbu_businessunitpvo T1000008
                            INNER JOIN cat_ocloud_dv.rg1glofsn_cz.fscm_fin_xle_legalentityextractpvo T1000011
                            ON T1000008.LEGALENTITYLEGALENTITYIDENTIFIER=T1000011.LEGALENTITYLEGALENTITYIDENTIFIER
                            WHERE T1000011.LEGALENTITYLEGALEMPLOYERFLAG = 'Y'
                            AND UPPER(T1000011.LEGALENTITYNAME) = upper({p_entidad_legal})
                            GROUP BY T1000008.BUSINESSUNITID
                            )
  GROUP BY 
          arps.arpaymentschedulecustomertrxid, arps.arpaymentschedulegldate, 
          case  arps.arpaymentschedulestatus when 'VD' then arps.arpaymentschedulestatus else ' ' end
),


impuestos_add AS (
      SELECT 
            rctla.RACUSTOMERTRXLINECUSTOMERTRXID as RACUSTOMERTRXCUSTOMERTRXID
            ,rctla.RACUSTOMERTRXLINELINKTOCUSTTRXLINEID
            ,RCTLGDA.RACUSTTRXLINEGLDISTGLDATE
            ,ZL.DETAILTAXLINETAXRATECODE
            ,GCC.codecombinationSEGMENT4 || '.' || GCC.codecombinationSEGMENT5 || '.' || GCC.codecombinationSEGMENT6 CTA_CONTABLE
            ,DECODE(RCTA.RaCustomerTrxExchangeRate, NULL, ZL.DetailTaxLineTaxAmt, ZL.DetailTaxLineTaxAmtFunclCurr) IMPUESTO_MXN
            ,DECODE(RCTA.RaCustomerTrxExchangeRate, NULL, 0, ZL.DetailTaxLineTaxAmt) IMPUESTO_ME
      FROM
          cat_ocloud_dv.rg1glofsn_cz.fscm_fin_ar_transactionheaderextractpvo RCTA          
      INNER JOIN cat_ocloud_dv.rg1glofsn_cz.fscm_fin_ar_transactionlineextractpvo RCTLA
          ON
              RCTA.RACUSTOMERTRXORGID = (select  T1000008.BUSINESSUNITID
                                         from   cat_ocloud_dv.rg1glofsn_cz.crm_ffbu_businessunitpvo T1000008
                                         INNER JOIN cat_ocloud_dv.rg1glofsn_cz.fscm_fin_xle_legalentityextractpvo T1000011
                                         ON T1000008.LEGALENTITYLEGALENTITYIDENTIFIER=T1000011.LEGALENTITYLEGALENTITYIDENTIFIER
                                         WHERE T1000011.LEGALENTITYLEGALEMPLOYERFLAG = 'Y'
                                         AND UPPER(T1000011.LEGALENTITYNAME) = upper({p_entidad_legal})
                                         GROUP BY T1000008.BUSINESSUNITID
                                        )
          AND RCTA.RaCustomerTrxCustomerTrxId = RCTLA.RACUSTOMERTRXLINECUSTOMERTRXID
          AND   RCTLA.RACUSTOMERTRXLINELINETYPE = 'TAX'
            INNER JOIN cat_ocloud_dv.rg1glofsn_cz.fscm_fin_ar_transactiondistributionextractpvo RCTLGDA
          ON  RCTLA.RACUSTOMERTRXLINECUSTOMERTRXID = RCTLGDA.RaCustTrxLineGlDistCUSTOMERTRXID
                AND RCTLA.RACUSTOMERTRXLINECUSTOMERTRXLINEID = RCTLGDA.RaCustTrxLineGlDistCustomerTrxLineId
            INNER JOIN cat_ocloud_dv.rg1glofsn_cz.fscm_fin_zx_detailtaxlineextractpvo ZL
          ON  RCTLA.RACUSTOMERTRXLINETAXLINEID = ZL.DetailTaxLineTAXLINEID  
                AND RCTLA.RACUSTOMERTRXLINELINKTOCUSTTRXLINEID = ZL.DetailTaxLineTRXLINEID  
            INNER JOIN cat_ocloud_dv.rg1glofsn_cz.fscm_fgacc_codecombinationpvo GCC
          ON GCC.codecombinationid = RCTLGDA.RaCustTrxLineGlDistCODECOMBINATIONID
            WHERE   1 = 1
            AND (   ((ZL.DetailTaxLineTAXRATECODE LIKE '%AR' AND (ZL.DetailTaxLineTAXRATECODE LIKE 'MX_IEPS%')) OR (ZL.DetailTaxLineTAXRATECODE LIKE '%IC' AND (ZL.DetailTaxLineTAXRATECODE LIKE 'MX_IEPS%')))
      or        ((ZL.DetailTaxLineTAXRATECODE LIKE '%AR' AND (ZL.DetailTaxLineTAXRATECODE LIKE 'MX_IVA%')) OR (ZL.DetailTaxLineTAXRATECODE LIKE '%IC%' AND (ZL.DetailTaxLineTAXRATECODE LIKE 'MX_IVA%')))
      or   (ZL.DetailTaxLineTAXRATECODE LIKE 'MX_RET_IR%')
      OR   (ZL.DetailTaxLineTAXRATECODE LIKE 'MX_RET_IVA%')
      )

      /*PERIODO CONTABLE-test_new_filter_time*/
  AND ((DECODE(date_format({p_periodo_contable_from},'yyyy-MM-dd HH24:mm:SS'),NULL,date_format('1900-01-01 00:00:00','yyyy-MM-dd HH24:mm:SS')
      ,date_format(RCTLGDA.racusttrxlinegldistgldate,'yyyy-MM-dd HH24:mm:SS')) 
      between NVL(date_format({p_periodo_contable_from}, 'yyyy-MM-dd HH24:mm:SS'),date_format('1900-01-01 00:00:00','yyyy-MM-dd HH24:mm:SS')) 
      and NVL(date_format({p_periodo_contable_to}, 'yyyy-MM-dd HH24:mm:SS'), date_format('1900-01-01 00:00:00','yyyy-MM-dd HH24:mm:SS'))
      ) OR RCTLGDA.racusttrxlinegldistgldate IS NULL)


  GROUP BY 
  rctla.RACUSTOMERTRXLINECUSTOMERTRXID
            ,rctla.RACUSTOMERTRXLINELINKTOCUSTTRXLINEID
            ,RCTLGDA.RACUSTTRXLINEGLDISTGLDATE
            ,ZL.DETAILTAXLINETAXRATECODE
            ,GCC.codecombinationSEGMENT4 || '.' || GCC.codecombinationSEGMENT5 || '.' || GCC.codecombinationSEGMENT6 
            ,DECODE(RCTA.RaCustomerTrxExchangeRate, NULL, ZL.DetailTaxLineTaxAmt, ZL.DetailTaxLineTaxAmtFunclCurr) 
            ,DECODE(RCTA.RaCustomerTrxExchangeRate, NULL, 0, ZL.DetailTaxLineTaxAmt) 
)

/*NUEVOS*/
,TRX_APP AS (SELECT arreceivableapplicationappliedcustomertrxid,
                       'APP' APP_TRX,
                       Count(*)
                FROM   cat_ocloud_dv.rg1glofsn_cz.fscm_fin_ar_receivableapplicationextractpvo RAA
                WHERE  1 = 1
                       AND arreceivableapplicationstatus = 'APP'
                       AND arreceivableapplicationdisplay = 'Y'
                GROUP  BY ARRECEIVABLEAPPLICATIONAPPLIEDCUSTOMERTRXID,
                          'APP'
               )
,TRX_CM AS (SELECT racustomertrxpreviouscustomertrxid,
                       racustomertrxorgid,
                       Count(*) CONTEO
                FROM   cat_ocloud_dv.rg1glofsn_cz.fscm_fin_ar_transactionheaderextractpvo TRX_CM
                WHERE  racustomertrxtrxclass = 'CM'
                GROUP  BY racustomertrxpreviouscustomertrxid,
                          racustomertrxorgid
               )


,IVA AS(SELECT 
                            racustomertrxcustomertrxid,
                            racustomertrxlinelinktocusttrxlineid,
                            racusttrxlinegldistgldate,
                            detailtaxlinetaxratecode,
                            impuesto_mxn,
                            impuesto_me,
                            cta_contable
                    FROM    impuestos_add
                    WHERE   1 = 1
                    AND (   (detailtaxlinetaxratecode LIKE '%AR' AND ( detailtaxlinetaxratecode LIKE 'MX_IVA%'))
                         OR (detailtaxlinetaxratecode LIKE '%IC%' AND ( detailtaxlinetaxratecode LIKE 'MX_IVA%'))
                        )
                    )
,IEPS AS (SELECT racustomertrxcustomertrxid,
                               racustomertrxlinelinktocusttrxlineid,
                               racusttrxlinegldistgldate,
                               detailtaxlinetaxratecode,
                               impuesto_mxn,
                               impuesto_me,
                               cta_contable
                    FROM   impuestos_add
                    WHERE  1 = 1
                    AND (   (detailtaxlinetaxratecode LIKE '%AR' AND ( detailtaxlinetaxratecode LIKE 'MX_IEPS%' ))
                         OR (detailtaxlinetaxratecode LIKE '%IC' AND ( detailtaxlinetaxratecode LIKE 'MX_IEPS%' ))
                        )
                    )

,RET_IVA AS (SELECT racustomertrxcustomertrxid,
                               racustomertrxlinelinktocusttrxlineid,
                               racusttrxlinegldistgldate,
                               detailtaxlinetaxratecode,
                               impuesto_mxn,
                               impuesto_me,
                               cta_contable
                    FROM   impuestos_add
                    WHERE  1 = 1
                    AND (   ( detailtaxlinetaxratecode LIKE 'MX_RET_IVA%' )
                         OR ( detailtaxlinetaxratecode LIKE '%IC%' AND ( detailtaxlinetaxratecode LIKE 'MX_RET%'))
                        )
                    )

,RET_ISR AS (SELECT racustomertrxcustomertrxid,
                               racustomertrxlinelinktocusttrxlineid,
                               racusttrxlinegldistgldate,
                               detailtaxlinetaxratecode,
                               impuesto_mxn,
                               impuesto_me,
                               cta_contable
                    FROM   impuestos_add
                    WHERE  1 = 1
                    AND ( detailtaxlinetaxratecode LIKE 'MX_RET_IR%')
                    )

,CLASIF_IMPTOS AS (
            SELECT  IVA.racustomertrxcustomertrxid,
                    IVA.racustomertrxlinelinktocusttrxlineid,
                    IVA.racusttrxlinegldistgldate,
                    IVA.detailtaxlinetaxratecode     CLASIF_IMPUESTO,
                    RET_IVA.detailtaxlinetaxratecode CLASIF_IVA_RET,
                    RET_ISR.detailtaxlinetaxratecode CLASIF_ISR_RET,
                    IVA.impuesto_mxn                 IVA_IMPUESTO_MX,
                    IVA.impuesto_me                  IVA_IMPUESTO_ME,
                    RET_IVA.impuesto_mxn             RET_IVA_IMPUESTO_MXN,
                    RET_IVA.impuesto_me              RET_IVA_IMPUESTO_ME,
                    RET_ISR.impuesto_mxn             RET_ISR_IMPUESTO_MXN,
                    RET_ISR.impuesto_me              RET_ISR_IMPUESTO_ME,
                    IEPS.impuesto_mxn                IEPS_IMPUESTO_MXN,
                    IEPS.impuesto_me                 IEPS_IMPUESTO_ME,
                    IVA.cta_contable                 CTA_CONTABLE_IVA,
                    RET_IVA.cta_contable             CTA_CONTABLE_RET_IVA,
                    RET_ISR.cta_contable             CTA_CONTABLE_RET_ISR,
                    IEPS.cta_contable                CTA_CONTABLE_IEPS
            FROM   IVA
            LEFT JOIN 
                    IEPS
                ON  IVA.racustomertrxcustomertrxid = IEPS.racustomertrxcustomertrxid 
                AND IVA.racustomertrxlinelinktocusttrxlineid = IEPS.racustomertrxlinelinktocusttrxlineid 
                AND IVA.racusttrxlinegldistgldate = IEPS.racusttrxlinegldistgldate 
            LEFT JOIN 
                    RET_IVA
                ON  IVA.racustomertrxcustomertrxid = RET_IVA.racustomertrxcustomertrxid
                AND IVA.racustomertrxlinelinktocusttrxlineid = RET_IVA.racustomertrxlinelinktocusttrxlineid
                AND IVA.racusttrxlinegldistgldate = RET_IVA.racusttrxlinegldistgldate
            LEFT JOIN
                    RET_ISR
            ON IVA.racustomertrxcustomertrxid = RET_ISR.racustomertrxcustomertrxid
            AND IVA.racustomertrxlinelinktocusttrxlineid = RET_ISR.racustomertrxlinelinktocusttrxlineid
            AND IVA.racusttrxlinegldistgldate = RET_ISR.racusttrxlinegldistgldate
          ) 


,FACTURAS as

(
     SELECT  
        RAGDA.racusttrxlinegldistcusttrxlinegldistid                                          racusttrxlinegldistcusttrxlinegldistid,
        RA.racustomertrxorgid                                                                 racustomertrxorgid,
        RA.racustomertrxcustomertrxid                                                         CUSTOMER_TRX_ID_RA,
        RA.racustomertrxtrxnumber                                                             NUMERO_TRANSACCION,
        RAL.racustomertrxlinelinenumber                                                       NUMERO_LINEA_TRANSACCION,
        RA.racustomertrxbatchsourceseqid                                                      RABATCHBATCHSOURCESEQID,
        CLTRX_LOOKUP.lookup_meaning                                                           CLASE_TRANSACCION,
        racustomertrxcompleteflag                                                             COMPLETADA,
        Decode(racustomertrxprintingpending,'N','Si','No') || ' ' || IMPRESA_LOOKUP.lookup_meaning   IMPRESA,
        RACTT.transactiontypename                                                             TIPO_TRANSACCION,
        RA.racustomertrxbilltocustomerid                                                      RACUSTOMERTRXBILLTOCUSTOMERID,
        racustomertrxinvoicecurrencycode                                                      MONEDA_RA,
        RA.racustomertrxexchangedate                                                          FECHA_TC_TRX,
        RA.racustomertrxexchangeratetype                                                      CLASE_TC_TRX,
        RA.racustomertrxexchangerate                                                          TC_TRX,
        RA.racustomertrxtrxdate                                                               FECHA_TRANSACCION,
        RAGDA.racusttrxlinegldistgldate                                                       FECHA_CONTABLE,
        racustomertrxattributecategory                                                        VALOR_CONTEXTO,
        racustomertrxattribute4                                                               USO_CFDI,
        racustomertrxattribute5                                                               METODO_PAGO,
        racustomertrxattribute6                                                               FORMAS_PAGO,
        racustomertrxattribute7                                                               TIPO_RELACION,
        racustomertrxglobalattribute1                                                         UUID_RELACIONADO,
        ESIB.inventoryitembasepeoitemnumber                                                        ARTICULO,
        RAL.racustomertrxlinedescription                                                      DESCRIPCION_ARTICULO,
        UOM.invuomtlpeounitofmeasure                                                          UNIDAD_MEDIDA,
        Nvl(clasif_impuesto, ' ')                                                             CLASIFICACION_IMPUESTOS,
        clasif_iva_ret                                                                        CLASIF_IVA_RET,
        clasif_isr_ret                                                                        CLASIF_ISR_RET,

        CASE WHEN RA.racustomertrxexchangerate IS NULL 
              THEN RAGDA.racusttrxlinegldistamount 
              ELSE RAGDA.racusttrxlinegldistacctdamount END                                   INGRESO_MX,

        CASE WHEN RA.racustomertrxexchangerate IS NULL 
              THEN 0 ELSE RAGDA.racusttrxlinegldistamount END                                 INGRESO_ME,
        CCOMB.codecombinationsegment4 || '.' || CCOMB.codecombinationsegment5 || '.'
        || CCOMB.codecombinationsegment6                                                      CTA_CONTABLE_INGRESO,
        iva_impuesto_mx                                                                       IVA_IMPUESTO_MX,
        iva_impuesto_me                                                                       IVA_IMPUESTO_ME,
        0                                                                                     IMPUESTO_IVA_COB_MXN,
        0                                                                                     IMPUESTO_IVA_COB_ME,
        0                                                                                     IMPUESTO_IVA_VALUACION,
        Nvl(cta_contable_iva, 0)                                                              CTA_CONTABLE_IVA,
        ieps_impuesto_mxn                                                                     IEPS_IMPUESTO_MXN,
        ieps_impuesto_me                                                                      IEPS_IMPUESTO_ME,
        0                                                                                     IMPUESTO_RET_IEPS_MXN,
        0                                                                                     IMPUESTO_RET_IEPS_ME,
        0                                                                                     IMPUESTO_IEPS_VALMON,
        Nvl(cta_contable_ieps, 0)                                                             CTA_CONTABLE_IEPS,
        ret_iva_impuesto_mxn                                                                  RET_IVA_IMPUESTO_MXN,
        ret_iva_impuesto_me                                                                   RET_IVA_IMPUESTO_ME,
        0                                                                                     RETENCION_IVA_VALMON,
        Nvl(cta_contable_ret_iva, 0)                                                          CTA_CONTABLE_RET_IVA,
        ret_isr_impuesto_mxn                                                                  RET_ISR_IMPUESTO_MXN,
        ret_isr_impuesto_me                                                                   RET_ISR_IMPUESTO_ME,
        0                                                                                     RETENCION_ISR_VALMON,
        cta_contable_ret_isr                                                                  CTA_CONTABLE_RET_ISR,
        RAL.racustomertrxlinetaxclassificationcode                                            RACUSTOMERTRXLINETAXCLASSIFICATIONCODE
        /*RAGDA.racusttrxlinegldistcodecombinationid                                            CODECOMB,
        TRX_APP.app_trx                                                                       PAGADA2,
        TRX_CM.conteo                                                                         ACREDITADA,
        NULL                                                                                  ANULAR,
        NULL                                                                                  IMPORTE_MX,
        NULL                                                                                  IMPORTE_ME,
        NULL                                                                                  HACER_CALCULOS,
        RACTT.transactiontypetype                                                             TIPO_TRANSAC,
        NULL                                                                                  AMOUNT_DUE_MXN,
        NULL                                                                                  AMOUNT_DUE_ME,*/
        ,CASE WHEN nvl(arps.arpaymentscheduleamountdueremaining, 0) = 0 
                THEN'PT'
                ELSE CASE WHEN TRX_APP.app_trx IS NULL THEN 'NP'
                      ELSE 'PP'
                  END END PAGADA2,
          CASE WHEN TRX_CM.conteo = 0 
                THEN 'No Acreditada'
                ELSE
                  CASE
                      WHEN abs((nvl(arps.arpaymentscheduleamountadjusted, 0) + nvl(arps.arpaymentscheduleamountcredited,
                      0) + nvl(arps.arpaymentscheduleamountindispute, 0))) >= arps.arpaymentscheduleamountlineitemsoriginal
                      THEN 'Totalmente Acreditada'
                      ELSE 'Parcialmente Acreditada'
                  END END ACREDITADA,
        CASE WHEN arps.arpaymentschedulestatus = 'VD' 
              THEN 'SI' ELSE 'NO' END ANULAR,

        nvl(RA.racustomertrxexchangerate, 1) * arps.arpaymentscheduleamountdueoriginal                                                                                 IMPORTE_MX,
        
        
          CASE WHEN RA.racustomertrxexchangerate != 0 
                THEN arps.arpaymentscheduleamountdueoriginal ELSE 0 END IMPORTE_ME,
        decode(RA.racustomertrxexchangerate, NULL
                  ,arps.arpaymentscheduleamountdueremaining
                  ,(arps.arpaymentscheduleamountdueremaining * RA.racustomertrxexchangerate))  AS AMOUNT_DUE_MXN,
          decode(RA.racustomertrxexchangerate, NULL, 0, arps.arpaymentscheduleamountdueremaining) AS AMOUNT_DUE_ME
    FROM
        cat_ocloud_dv.rg1glofsn_cz.fscm_fin_ar_transactionheaderextractpvo RA
    INNER JOIN 
        cat_ocloud_dv.rg1glofsn_cz.fscm_fin_ar_transactionlineextractpvo RAL
        ON RA.racustomertrxcustomertrxid = RAL.racustomertrxlinecustomertrxid
        AND RAL.racustomertrxlinelinetype = 'LINE'
    INNER JOIN 
        cat_ocloud_dv.rg1glofsn_cz.fscm_fin_ar_transactiondistributionextractpvo RAGDA
        ON RAL.racustomertrxlinecustomertrxid = RAGDA.racusttrxlinegldistcustomertrxid
        AND RAL.racustomertrxlinecustomertrxlineid = RAGDA.racusttrxlinegldistcustomertrxlineid
        AND RAGDA.racusttrxlinegldistglposteddate IS NOT NULL
    INNER JOIN 
        cat_ocloud_dv.rg1glofsn_cz.fscm_finar_transactiontypepvo RACTT
        ON RA.racustomertrxcusttrxtypeseqid = RACTT.custtrxtypeseqid
    INNER JOIN 
        cat_ocloud_dv.rg1glofsn_cz.fscm_fgacc_codecombinationpvo CCOMB
        ON RAGDA.racusttrxlinegldistcodecombinationid = CCOMB.codecombinationid
    INNER JOIN ar_payment_schedule arps/*NEW*/
      ON ra.racustomertrxcustomertrxid = arps.arpaymentschedulecustomertrxid
    LEFT JOIN 
        cat_ocloud_dv.rg1glofsn_cz.fscm_egp_inventoryitemref ESIB
        ON RAL.racustomertrxlineinventoryitemid = ESIB.inventoryitemid
        AND RAL.racustomertrxlinewarehouseid = ESIB.organizationid
    LEFT JOIN 
        cat_ocloud_dv.rg1glofsn_cz.fscm_invuom_invuompvo UOM
        ON RAL.racustomertrxlineuomcode = UOM.invuombpeouomcode
        AND invuomtlpeolanguage = 'E'
    LEFT JOIN TRX_APP
              ON RA.racustomertrxcustomertrxid = TRX_APP.arreceivableapplicationappliedcustomertrxid
    LEFT JOIN TRX_CM
         ON RA.racustomertrxcustomertrxid = TRX_CM.racustomertrxpreviouscustomertrxid
             AND RA.racustomertrxorgid = TRX_CM.racustomertrxorgid
    LEFT JOIN 
         {@CATALOG}.{@SCHEMA}.cat_fnd_lookup CLTRX_LOOKUP
           ON CLTRX_LOOKUP.view_application_id  = 222
               AND CLTRX_LOOKUP.language  = 'E'
               AND CLTRX_LOOKUP.set_id  = 0
               AND CLTRX_LOOKUP.lookup_code  = RACTT.transactiontypetype
               AND CLTRX_LOOKUP.lookup_type  = 'INV/CM'
    LEFT JOIN
         {@CATALOG}.{@SCHEMA}.cat_fnd_lookup IMPRESA_LOOKUP
           ON IMPRESA_LOOKUP.view_application_id  = 222
               AND IMPRESA_LOOKUP.language  = 'E'
               AND IMPRESA_LOOKUP.set_id  = 0
               AND IMPRESA_LOOKUP.lookup_code  = RA.racustomertrxdeliverymethodcode
               AND IMPRESA_LOOKUP.lookup_type  = 'AR_INV_DELIVERY_METHOD'
    LEFT JOIN 
          CLASIF_IMPTOS
          ON RAL.racustomertrxlinecustomertrxid = CLASIF_IMPTOS.racustomertrxcustomertrxid
          AND RAL.racustomertrxlinecustomertrxlineid =CLASIF_IMPTOS.racustomertrxlinelinktocusttrxlineid 
          AND RAGDA.racusttrxlinegldistgldate = CLASIF_IMPTOS.racusttrxlinegldistgldate 

    WHERE 1=1
    AND RAGDA.racusttrxlinegldistcusttrxlinegldistid NOT IN (1542851075, 1542983802, 1542983508, 1542851088,1542984699, 1542983514, 1542984693, 1542983513,
                                                              1927932965, 2016436973, 2205668101, 2205668102,2234557894, 2228199792, 2736585302, 2938791406,2938791414)

    /*Parametro de Entidad-test_new_filter_time*/
    and ra.RACUSTOMERTRXORGID = (select T1000008.BUSINESSUNITID
                            from 
                                 cat_ocloud_dv.rg1glofsn_cz.crm_ffbu_businessunitpvo T1000008
                            INNER JOIN cat_ocloud_dv.rg1glofsn_cz.fscm_fin_xle_legalentityextractpvo T1000011
                            ON T1000008.LEGALENTITYLEGALENTITYIDENTIFIER=T1000011.LEGALENTITYLEGALENTITYIDENTIFIER
                            WHERE T1000011.LEGALENTITYLEGALEMPLOYERFLAG = 'Y'
                            AND UPPER(T1000011.LEGALENTITYNAME) = upper({p_entidad_legal})
                            GROUP BY T1000008.BUSINESSUNITID
                            )
    /*PERIODO CONTABLE-test_new_filter_time*/
  AND ((DECODE(date_format({p_periodo_contable_from},'yyyy-MM-dd HH24:mm:SS'),NULL,date_format('1900-01-01 00:00:00','yyyy-MM-dd HH24:mm:SS')
      ,date_format(RAGDA.racusttrxlinegldistgldate,'yyyy-MM-dd HH24:mm:SS')) 
      between NVL(date_format({p_periodo_contable_from}, 'yyyy-MM-dd HH24:mm:SS'),date_format('1900-01-01 00:00:00','yyyy-MM-dd HH24:mm:SS')) 
      and NVL(date_format({p_periodo_contable_to}, 'yyyy-MM-dd HH24:mm:SS'), date_format('1900-01-01 00:00:00','yyyy-MM-dd HH24:mm:SS'))
      ) OR RAGDA.racusttrxlinegldistgldate IS NULL)





GROUP BY 

 RAGDA.racusttrxlinegldistcusttrxlinegldistid                                          ,
        RA.racustomertrxorgid                                                                 ,
        RA.racustomertrxcustomertrxid                                                         ,
        RA.racustomertrxtrxnumber                                                             ,
        RAL.racustomertrxlinelinenumber                                                       ,
        RA.racustomertrxbatchsourceseqid                                                      ,
        CLTRX_LOOKUP.lookup_meaning                                                           ,
        racustomertrxcompleteflag                                                             ,
        Decode(racustomertrxprintingpending,'N','Si','No') || ' ' || IMPRESA_LOOKUP.lookup_meaning   ,
        RACTT.transactiontypename                                                             ,
        RA.racustomertrxbilltocustomerid                                                      ,
        racustomertrxinvoicecurrencycode                                                      ,
        RA.racustomertrxexchangedate                                                          ,
        RA.racustomertrxexchangeratetype                                                      ,
        RA.racustomertrxexchangerate                                                          ,
        RA.racustomertrxtrxdate                                                               ,
        RAGDA.racusttrxlinegldistgldate                                                       ,
        racustomertrxattributecategory                                                        ,
        racustomertrxattribute4                                                               ,
        racustomertrxattribute5                                                               ,
        racustomertrxattribute6                                                               ,
        racustomertrxattribute7                                                               ,
        racustomertrxglobalattribute1                                                         ,
        ESIB.inventoryitembasepeoitemnumber                                                        ,
        RAL.racustomertrxlinedescription                                                      ,
        UOM.invuomtlpeounitofmeasure                                                          ,
        Nvl(clasif_impuesto, ' ')                                                             ,
        clasif_iva_ret                                                                        ,
        clasif_isr_ret                                                                        ,
        CASE WHEN RA.racustomertrxexchangerate IS NULL 
              THEN RAGDA.racusttrxlinegldistamount 
              ELSE RAGDA.racusttrxlinegldistacctdamount END                                   ,
        CASE WHEN RA.racustomertrxexchangerate IS NULL 
              THEN 0 ELSE RAGDA.racusttrxlinegldistamount END                                 ,
        CCOMB.codecombinationsegment4 || '.' || CCOMB.codecombinationsegment5 || '.'
        || CCOMB.codecombinationsegment6                                                      ,
        iva_impuesto_mx                                                                       ,
        iva_impuesto_me                                                                       ,
        Nvl(cta_contable_iva, 0)                                                              ,
        ieps_impuesto_mxn                                                                     ,
        ieps_impuesto_me                                                                      ,
        Nvl(cta_contable_ieps, 0)                                                             ,
        ret_iva_impuesto_mxn                                                                  ,
        ret_iva_impuesto_me                                                                   ,
        Nvl(cta_contable_ret_iva, 0)                                                          ,
        ret_isr_impuesto_mxn                                                                  ,
        ret_isr_impuesto_me                                                                   ,
        cta_contable_ret_isr                                                                  ,
        RAL.racustomertrxlinetaxclassificationcode                                            
        ,CASE WHEN nvl(arps.arpaymentscheduleamountdueremaining, 0) = 0 
                THEN'PT'
                ELSE CASE WHEN TRX_APP.app_trx IS NULL THEN 'NP'
                      ELSE 'PP'
                  END END 
        ,CASE WHEN TRX_CM.conteo = 0 
                THEN 'No Acreditada'
                ELSE
                  CASE
                      WHEN abs((nvl(arps.arpaymentscheduleamountadjusted, 0) + nvl(arps.arpaymentscheduleamountcredited,
                      0) + nvl(arps.arpaymentscheduleamountindispute, 0))) >= arps.arpaymentscheduleamountlineitemsoriginal
                      THEN 'Totalmente Acreditada'
                      ELSE 'Parcialmente Acreditada'
                  END END 
                  
      ,CASE WHEN arps.arpaymentschedulestatus = 'VD' THEN 'SI' ELSE 'NO' END
      ,nvl(RA.racustomertrxexchangerate, 1) * arps.arpaymentscheduleamountdueoriginal
      ,CASE WHEN RA.racustomertrxexchangerate != 0 THEN arps.arpaymentscheduleamountdueoriginal ELSE 0 END
      ,decode(RA.racustomertrxexchangerate, NULL, arps.arpaymentscheduleamountdueremaining,(arps.arpaymentscheduleamountdueremaining * RA.racustomertrxexchangerate))
      ,decode(RA.racustomertrxexchangerate, NULL, 0, arps.arpaymentscheduleamountdueremaining) 



),


COBROS AS(
  SELECT 
          CUSTOMER_TRX_ID_CO,
          APPLICATION_TYPE,
          NUMERO_COBRO,
          FECHA_COBRO,
          FECHA_COBRO_DEPOSITO FECHA_COBRO_DEPOSITO,
          FECHA_APLICACION,
          MONEDA_COBRO,
          FECHA_TIPO_CAMBIO,
          CLASE_TIPO_CAMBIO,
          TIPO_CAMBIO,
          DECODE(MONEDA_COBRO, 'MXN', AMOUNT, (AMOUNT * TIPO_CAMBIO)) AS IMPORTE_COBRO_MXN,
          (CASE WHEN TIPO_CAMBIO <> 0 THEN AMOUNT ELSE 0 END) AS IMPORTE_COBRO_ME,
          DECODE(MONEDA_COBRO, 'MXN', MONTO_APLICADO_CALC, (MONTO_APLICADO_CALC * TIPO_CAMBIO)) AS IMPORTE_APLICADO_MXN,
          (CASE WHEN TIPO_CAMBIO <> 0 THEN MONTO_APLICADO_CALC ELSE 0 END) AS IMPORTE_APLICADO_ME,
          MONTO_APLICADO_CALC,
          IMPORTE_COBRO_CUST,
          COBRO_CFDI,
          COMBRO_IMP_ID_UNICO,
          CASH_RECEIPT_ID,
          RECEIPT_METHOD_ID,
          IMPORTE_MXN,
          RCPT_EXCHG_RATE,
          RCPT_ID,
          BankAccountBankAccountName BANK_ACCOUNT_NAME,
          RCPT_PAYMENT_TRXN_EXTENSION_ID,
          PAYMENT_NUMBER,
          TRX_NUMBER_CO,
          FECHA_CTABLE_DEP,
          (CASE WHEN APPLICATION_TYPE = 'CM' THEN 'Nota de Credito' ELSE ESTADO2 END)  ESTADO,
          ESTADO2,
          REF_PAGO_ESTRUCT,
          INFORMACION_REG,
          BankBankName BANK_NAME,
          COMB_CONT_COBRO_IVA,
          COMB_CONT_COBRO_IEPS,
          RECEIPT_NUMBER
          ,FECHA_REVERSA

          ,CodeCombinationSegment6  ------------------!!!!!!!!!!!
          ,CodeCombinationSegment6_ieps

  from (
        SELECT 
                CHIS.ARCASHRECEIPTHISTORYSTATUS, RAA.ARRECEIVABLEAPPLICATIONCASHRECEIPTHISTORYID, CR.ARCASHRECEIPTCASHRECEIPTID, 
                RA.RACUSTOMERTRXCUSTOMERTRXID CUSTOMER_TRX_ID_CO, 
                ARRECEIVABLEAPPLICATIONRECEIVABLEAPPLICATIONID, RAA.ARRECEIVABLEAPPLICATIONEVENTID, RAA.ARRECEIVABLEAPPLICATIONAPPLIEDCUSTOMERTRXID
                ,RAA.ARRECEIVABLEAPPLICATIONAPPLICATIONTYPE APPLICATION_TYPE
                ,(CASE
                WHEN RAA.ARRECEIVABLEAPPLICATIONAPPLICATIONTYPE = 'CM' THEN RACM.RACUSTOMERTRXTRXNUMBER 
                ELSE CR.ARCASHRECEIPTRECEIPTNUMBER
                END) AS NUMERO_COBRO
                ,NVL(CR.ARCASHRECEIPTRECEIPTDATE, RAA.ARRECEIVABLEAPPLICATIONAPPLYDATE) AS FECHA_COBRO
                ,CR.ARCASHRECEIPTDEPOSITDATE AS FECHA_COBRO_DEPOSITO
                ,RAA.ARRECEIVABLEAPPLICATIONAPPLYDATE FECHA_APLICACION
                ,( CASE
                  WHEN RAA.ARRECEIVABLEAPPLICATIONAPPLICATIONTYPE = 'CM' THEN RACM.RACUSTOMERTRXINVOICECURRENCYCODE 
                ELSE CR.ARCASHRECEIPTCURRENCYCODE
                END) AS MONEDA_COBRO
                ,( CASE
                  WHEN RAA.ARRECEIVABLEAPPLICATIONAPPLICATIONTYPE = 'CM' THEN  RA.RACUSTOMERTRXEXCHANGEDATE 
                ELSE CR.ARCASHRECEIPTEXCHANGEDATE
                END) AS FECHA_TIPO_CAMBIO
                ,(CASE
                  WHEN RAA.ARRECEIVABLEAPPLICATIONAPPLICATIONTYPE = 'CM' THEN RA.RACUSTOMERTRXEXCHANGERATETYPE 
                ELSE CR.ARCASHRECEIPTEXCHANGERATETYPE
                END) AS CLASE_TIPO_CAMBIO
                ,(CASE
                  WHEN RAA.ARRECEIVABLEAPPLICATIONAPPLICATIONTYPE = 'CM' THEN RA.RACUSTOMERTRXEXCHANGERATE 
                ELSE CR.ARCASHRECEIPTEXCHANGERATE
                END) AS TIPO_CAMBIO
                ,NVL(CR.ARCASHRECEIPTAMOUNT, RAA.ARRECEIVABLEAPPLICATIONAMOUNTAPPLIED) AS AMOUNT
                ,RAA.ARRECEIVABLEAPPLICATIONAMOUNTAPPLIED AS MONTO_APLICADO_CALC
                ,RAA.ARRECEIVABLEAPPLICATIONAMOUNTAPPLIED AS IMPORTE_COBRO_CUST
                ,CR.ARCASHRECEIPTATTRIBUTE8 AS COBRO_CFDI
                ,CR.ARCASHRECEIPTGLOBALATTRIBUTE1 AS COMBRO_IMP_ID_UNICO
                ,CR.ARCASHRECEIPTCASHRECEIPTID AS CASH_RECEIPT_ID
                ,CR.ARCASHRECEIPTRECEIPTMETHODID AS RECEIPT_METHOD_ID
                ,CR.ARCASHRECEIPTAMOUNT AS IMPORTE_MXN
                ,CR.ARCASHRECEIPTEXCHANGERATE AS RCPT_EXCHG_RATE
                ,CR.ARCASHRECEIPTCASHRECEIPTID AS RCPT_ID
                ----,BACC.BankAccountBankAccountName
                ,CBAE.BankAccountReportPEOBankAccountName AS BankAccountBankAccountName ------------!!!!!!!!!!!!!
                ,CR.ARCASHRECEIPTPAYMENTTRXNEXTENSIONID AS RCPT_PAYMENT_TRXN_EXTENSION_ID
                ,CR.ARCASHRECEIPTRECEIPTNUMBER AS PAYMENT_NUMBER
                ,RA.RACUSTOMERTRXTRXNUMBER AS TRX_NUMBER_CO
                ,RAA.ARRECEIVABLEAPPLICATIONGLDATE AS FECHA_CTABLE_DEP
                ,RECSTATUS_LOOKUP.MEANING ESTADO
                ,CHISTAT.ARCASHRECEIPTHISTORYSTATUS ESTADO2
                ,CR.ARCASHRECEIPTSTRUCTUREDPAYMENTREFERENCE AS REF_PAGO_ESTRUCT
                ,FLCON.NAME INFORMACION_REG
                -----,BACC.BankBankName
                ,CBBV.BANK_NAME AS BankBankName --------------!!!!!!!!!!!!!!!!!
                ,COMB_CONT_COBRO_IVA.COMB_CONT_COBRO COMB_CONT_COBRO_IVA
                ,COMB_CONT_COBRO_IEPS.COMB_CONT_COBRO COMB_CONT_COBRO_IEPS
                ,CR.ARCASHRECEIPTRECEIPTNUMBER RECEIPT_NUMBER
                ,RAA.ARRECEIVABLEAPPLICATIONREVERSALGLDATE FECHA_REVERSA

                ,COMB_CONT_COBRO_IVA.CodeCombinationSegment6 -------------------!!!!!!!!!!!!!!!
                ,COMB_CONT_COBRO_IEPS.CodeCombinationSegment6 CodeCombinationSegment6_ieps
                
        from cat_ocloud_dv.rg1glofsn_cz.fscm_fin_ar_transactionheaderextractpvo RA
        inner join cat_ocloud_dv.rg1glofsn_cz.fscm_fin_ar_receivableapplicationextractpvo  RAA
            on  RA.RACUSTOMERTRXCUSTOMERTRXID = RAA.ARRECEIVABLEAPPLICATIONAPPLIEDCUSTOMERTRXID
            AND RAA.ARRECEIVABLEAPPLICATIONSTATUS = 'APP'
        left join cat_ocloud_dv.rg1glofsn_cz.fscm_fin_ar_transactionheaderextractpvo RACM
            on RAA.ARRECEIVABLEAPPLICATIONCUSTOMERTRXID = RACM.RACUSTOMERTRXCUSTOMERTRXID
        left join cat_ocloud_dv.rg1glofsn_cz.fscm_fin_ar_receiptheaderextractpvo CR
            on RAA.ARRECEIVABLEAPPLICATIONCASHRECEIPTID = CR.ARCASHRECEIPTCASHRECEIPTID
        left join cat_ocloud_dv.rg1glofsn_cz.fscm_fin_ar_receipthistoryextractpvo CHIS
            on RAA.ARRECEIVABLEAPPLICATIONCASHRECEIPTHISTORYID = CHIS.ARCASHRECEIPTHISTORYCASHRECEIPTHISTORYID
        left join cat_ocloud_dv.rg1glofsn_cz.fscm_fin_ar_receipthistoryextractpvo CHISTAT
            on CR.ARCASHRECEIPTCASHRECEIPTID = CHISTAT.ARCASHRECEIPTHISTORYCASHRECEIPTID
            and CHISTAT.ARCASHRECEIPTHISTORYCURRENTRECORDFLAG = 'Y'
            and CHISTAT.ARCASHRECEIPTHISTORYREVERSALGLDATE IS NULL
        left join
                  (SELECT ARCASHRECEIPTHISTORYCASHRECEIPTID, COUNT(1) CONTEO
                  FROM cat_ocloud_dv.rg1glofsn_cz.fscm_fin_ar_receipthistoryextractpvo HIST
                  WHERE 1 = 1 
                  AND HIST.ARCASHRECEIPTHISTORYCURRENTRECORDFLAG = 'Y'
                  AND HIST.ARCASHRECEIPTHISTORYREVERSALGLDATE IS NULL
                  AND HIST.ARCASHRECEIPTHISTORYSTATUS = 'CLEARED' 
                  GROUP BY ARCASHRECEIPTHISTORYCASHRECEIPTID
                  ) CONTEO_HIST
            on CR.ARCASHRECEIPTCASHRECEIPTID  = CONTEO_HIST.ARCASHRECEIPTHISTORYCASHRECEIPTID
        LEFT JOIN cat_ocloud_dv.rg1glofsn_cz.fscm_as_lookupvaluestlpvo RECSTATUS_LOOKUP
            on RECSTATUS_LOOKUP.LOOKUPCODE = case when NVL(CONTEO_HIST.CONTEO,0) > 0 THEN 'CLEARED' ELSE CHIS.ARCASHRECEIPTHISTORYSTATUS END
            and RECSTATUS_LOOKUP.VIEWAPPLICATIONID = 222
            and RECSTATUS_LOOKUP.Language = 'E'
            and RECSTATUS_LOOKUP.SETID = 0
            and RECSTATUS_LOOKUP.LOOKUPTYPE = 'RECEIPT_CREATION_STATUS'

        /*new */
        LEFT JOIN COBROS_IMP COMB_CONT_COBRO_IVA
          ON RAA.ARRECEIVABLEAPPLICATIONAPPLIEDCUSTOMERTRXID = COMB_CONT_COBRO_IVA.ARRECEIVABLEAPPLICATIONAPPLIEDCUSTOMERTRXID
          AND COMB_CONT_COBRO_IVA.TIPO_IMPTO  = 'IVA'
        LEFT JOIN COBROS_IMP COMB_CONT_COBRO_IEPS
          ON RAA.ARRECEIVABLEAPPLICATIONAPPLIEDCUSTOMERTRXID = COMB_CONT_COBRO_IEPS.ARRECEIVABLEAPPLICATIONAPPLIEDCUSTOMERTRXID
          AND COMB_CONT_COBRO_IEPS.TIPO_IMPTO = 'IEPS'

          
        LEFT JOIN cat_ocloud_dv.rg1glofsn_cz.fscm_as_descrflexcontextstlpvo FLCON
          on CR.ARCASHRECEIPTGLOBALATTRIBUTECATEGORY=  FLCON.CONTEXTCODE
          and FLCON.LANGUAGE = 'E'
          and FLCON.DESCRIPTIVEFLEXFIELDCODE = 'JG_AR_CASH_RECEIPTS'
          and FLCON.APPLICATIONID = 7003
        LEFT JOIN cat_ocloud_dv.rg1glofsn_cz.fscm_fin_ce_bankaccountuseextractpvo BUSE
          on CR.ARCASHRECEIPTREMITBANKACCTUSEID = BUSE.BANKACCOUNTUSEPEOBANKACCTUSEID
      
        LEFT JOIN cat_ocloud_dv.rg1glofsn_cz.fscm_fin_ce_bankaccountextractpvo CBAE  --------------!!!!!!!!!!!!!!!!!
        ON  CBAE.BankAccountReportPEOBankAccountId =  BUSE.BANKACCOUNTUSEPEOBANKACCOUNTID   --------------!!!!!!!!!!!!!!!!!

      ----  LEFT JOIN cat_ocloud_dv.rg1glofsn_cz.fscm_fcbr_bankaccountpvo BACC 
      ----    on BUSE.BANKACCOUNTUSEPEOBANKACCOUNTID = BACC.BankAccountId

       LEFT JOIN cat_ocloud_dv.rg1glofsn_cz.ce_bank_branches_v CBBV  --------------!!!!!!!!!!!!!!!!!
       ON CBBV.BANK_PARTY_ID = CBAE.BankAccountReportPEOBankId  --------------!!!!!!!!!!!!!!!!!
       AND CBBV.BRANCH_PARTY_ID = CBAE.BankAccountReportPEOBankBranchId  --------------!!!!!!!!!!!!!!!!!
        /*Parametro de Entidad-test_new_filter_time*/
        where 1=1
        and ra.RACUSTOMERTRXORGID = (select T1000008.BUSINESSUNITID
                            from 
                                 cat_ocloud_dv.rg1glofsn_cz.crm_ffbu_businessunitpvo T1000008
                            INNER JOIN cat_ocloud_dv.rg1glofsn_cz.fscm_fin_xle_legalentityextractpvo T1000011
                            ON T1000008.LEGALENTITYLEGALENTITYIDENTIFIER=T1000011.LEGALENTITYLEGALENTITYIDENTIFIER
                            WHERE T1000011.LEGALENTITYLEGALEMPLOYERFLAG = 'Y'
                            AND UPPER(T1000011.LEGALENTITYNAME) = upper({p_entidad_legal})
                            GROUP BY T1000008.BUSINESSUNITID
                            )
      )
  where 1=1

/*PERIODO DE PAGO-test_new_filter_time*/
  AND ((DECODE(date_format({p_periodo_pago_from},'yyyy-MM-dd HH24:mm:SS'),NULL,date_format('1900-01-01 00:00:00','yyyy-MM-dd HH24:mm:SS')
      ,date_format(FECHA_COBRO,'yyyy-MM-dd HH24:mm:SS'))
      between NVL(date_format({p_periodo_pago_from}, 'yyyy-MM-dd HH24:mm:SS'),date_format('1900-01-01 00:00:00','yyyy-MM-dd HH24:mm:SS')) 
      and NVL(date_format({p_periodo_pago_to}, 'yyyy-MM-dd HH24:mm:SS'),date_format('1900-01-01 00:00:00','yyyy-MM-dd HH24:mm:SS'))
      ) OR FECHA_COBRO IS NULL)
),

SAWITH1 AS (
  select T1000008.BUSINESSUNITID as c1,
     T1000008.LEGALENTITYLEGALENTITYIDENTIFIER as c2
  from 
     cat_ocloud_dv.rg1glofsn_cz.crm_ffbu_businessunitpvo T1000008
  GROUP BY T1000008.BUSINESSUNITID
          ,T1000008.LEGALENTITYLEGALENTITYIDENTIFIER
),

SAWITH2 AS (
  select T1000011.LEGALENTITYLEGALEMPLOYERFLAG as c1,
     T1000011.LEGALENTITYLEINFORMATIONCONTEXT as c2,
     T1000011.LEGALENTITYNAME as c3,
     T1000011.LEGALENTITYLEGALENTITYIDENTIFIER as c4
  from 
       cat_ocloud_dv.rg1glofsn_cz.fscm_fin_xle_legalentityextractpvo T1000011
  where  ( T1000011.LEGALENTITYLEGALEMPLOYERFLAG = 'Y' 
  and UPPER(T1000011.LEGALENTITYNAME) = upper({p_entidad_legal})) 
),

-- >>> FACT: CORRECCION 2026-09-15 -- SAWITH3+SAWITH4 SI se sustituyen por el catalogo
-- cat_hz_customer_account (dimensiones/comunes/, referenciado directo). El descarte anterior
-- (ver nota del header del archivo, linea 16-20) se resolvio: cat_hz_customer_account usa
-- HZ_PARTIES directo (misma fuente
-- que ya usaban SAWITH3/SAWITH4), no la PVO con hueco de RUT -- ya no aplica esa objecion.
-- Validado en vivo: hz_parties.PARTY_NAME nunca es NULL (0 de 3,308,271 filas), por lo que
-- NVL(D5.c3,D5.c4) y el NVL(...,D4.c1) exterior en Cliente_facturacin (mas abajo) siempre resuelven
-- a PARTY_NAME -- D5.c4 (PARTY_UNIQUE_NAME, que cat_hz_customer_account no expone) y el fallback a
-- ACCOUNTNAME en D4.c1 son ramas muertas, confirmadas en vivo, no alcanzables.
-- SAWITH4 se reconstruye con SELECT DISTINCT sobre party_id: el catalogo esta grabado a nivel
-- cust_account_id (1 cliente puede tener varias cuentas -- validado en vivo: 2,274 party_id con mas
-- de 1 cuenta, 7,942 filas de cuenta extra), mientras que el SAWITH4 original leia hz_parties sola
-- (grano 1 fila por party_id); sin el DISTINCT el join D4.c3=D5.c2 duplicaria filas para esos
-- 2,274 terceros.
-- FIX: SAWITH3 — solo columnas usadas + GROUP BY para eliminar duplicados de cat_hz_customer_account
SAWITH3 AS (
  select NVL(cust_acct.party_name, cust_acct.account_name)  as c1,
     cust_acct.cust_account_id as c2,
     cust_acct.party_id as c3
  from
     {@CATALOG}.{@SCHEMA}.cat_hz_customer_account cust_acct
  WHERE (upper(cust_acct.account_name) IN (DECODE(upper({p_cliente}),'TODO',UPPER(cust_acct.account_name),upper({p_cliente}))) OR cust_acct.account_name IS NULL)
  OR  (upper(cust_acct.party_name) IN (DECODE(upper({p_cliente}),'TODO',UPPER(cust_acct.party_name),upper({p_cliente}))))
  GROUP BY cust_acct.party_name, cust_acct.account_name, cust_acct.cust_account_id, cust_acct.party_id
),

-- FIX: SAWITH4 — GROUP BY party_id + MAX para garantizar 1 fila por party_id
-- (equivalente a hz_parties original que es 1:1 por PARTY_ID)
SAWITH4 AS (
  select MAX(cust_acct.jgzz_fiscal_code) as c1,
     cust_acct.party_id as c2,
     MAX(cust_acct.party_name) AS c3,
     CAST(NULL AS STRING) AS c4 -- PARTY_UNIQUE_NAME original: rama muerta
  from
     {@CATALOG}.{@SCHEMA}.cat_hz_customer_account cust_acct
  WHERE 1=1
  AND (upper(cust_acct.jgzz_fiscal_code) IN (DECODE(upper({p_rfc_cliente}),'TODO',UPPER(cust_acct.jgzz_fiscal_code),upper({p_rfc_cliente}))) OR cust_acct.jgzz_fiscal_code IS NULL)
  GROUP BY cust_acct.party_id
),

SAWITH5 AS (
  select T1000020.RABATCHSOURCENAME as c1,
     T1000020.RABATCHSOURCEBATCHSOURCESEQID as c2
  from 
     cat_ocloud_dv.rg1glofsn_cz.fscm_fin_ar_transactionbatchsourceextractpvo T1000020
  WHERE 1=1
  AND (UPPER(T1000020.RABATCHSOURCENAME) IN (DECODE(upper({p_origen_transaccion}),'TODO',UPPER(T1000020.RABATCHSOURCENAME),upper({p_origen_transaccion})))  OR T1000020.RABATCHSOURCENAME IS NULL )
)






SELECT 
NUMERO_TRANSACCION AS Nmero_de_transaccin
,NULL AS Numero_linea_transaccin
,SAWITH5.c1 AS Origen_transaccin
,CLASE_TRANSACCION AS Clase_transaccin
,COMPLETADA AS Completada
,PAGADA2 AS Pagada
,ACREDITADA AS Acreditada
,IMPRESA AS Impresa
,ANULAR AS Anular
,TIPO_TRANSACCION AS Tipo_transaccin
,NVL(NVL(D5.c3,D5.c4),D4.c1) AS Cliente_facturacin

,CASE WHEN upper({p_tipo_reporte}) = 'REVERTIDO' AND POLO.PAGADA2 IN ('NP', 'PP', 'PT') AND POLO.ESTADO IN ('REVERSED')
  THEN CASE WHEN IMPORTE_APLICADO_MXN > 0 /*VALIDA LINEA BASE DE PAGO*/
      THEN IMPORTE_MX /*SI ES LINEA BASE SE MANTIENE IGUAL*/
            ELSE CASE WHEN IMPORTE_MX IS NOT NULL AND IMPORTE_MX != 0 
            THEN IMPORTE_MX * -1 
                      ELSE IMPORTE_MX 
                 END
         END
    ELSE IMPORTE_MX
END AS Importe_MXN1

,CASE WHEN upper({p_tipo_reporte}) = 'REVERTIDO' AND POLO.PAGADA2 IN ('NP', 'PP', 'PT') AND POLO.ESTADO IN ('REVERSED')
  THEN CASE WHEN IMPORTE_APLICADO_MXN > 0 /*VALIDA LINEA BASE DE PAGO*/
      THEN IMPORTE_ME /*SI ES LINEA BASE SE MANTIENE IGUAL*/
            ELSE CASE WHEN IMPORTE_ME IS NOT NULL AND IMPORTE_ME != 0 
            THEN IMPORTE_ME * -1 
                      ELSE IMPORTE_ME 
                 END
         END
    ELSE IMPORTE_ME
END AS Importe_ME1
,MONEDA_RA AS Moneda1
,FECHA_TC_TRX AS Fecha_cambio1
,CLASE_TC_TRX AS Clase_tipo_cambio1
,TC_TRX AS Tipo_cambio1
,FECHA_TRANSACCION AS Fecha_transaccin
,FECHA_CONTABLE AS Fecha_contable1
,D5.c1 AS Nmero_reg_fiscal_cliente_fact
,VALOR_CONTEXTO AS Valor_contexto
,USO_CFDI AS Uso_CFDI1
,METODO_PAGO AS Mtodo_Pago
,FORMAS_PAGO AS Formas_pago
,TIPO_RELACION AS Tipo_Relacin
,UUID_RELACIONADO AS UUID_Relacionado
,NULL AS Artculo
,NULL AS Descripcin
,NULL AS Unidad_medida
,CLASIFICACION_IMPUESTOS AS Clasificacin_impuestos
,CLASIF_IVA_RET AS Clasificacin_imp_IVA_ret
,CLASIF_ISR_RET AS Clasificacin_imp_ISR_ret
,cast( SUM(INGRESO_MX) as decimal(18,2)) AS Ingreso_MXN --------------!!!!!!!!!!!!!!!!!!! cambio 
,SUM(INGRESO_ME) AS Ingreso_ME
,SUM(INGRESO_VALMON) AS Ingreso_Valuacin_Monetaria
,CTA_CONTABLE_INGRESO AS Cuenta_contable_ingreso
,cast (SUM(IVA_IMPUESTO_MX) as decimal(18,2))  AS Impuesto_IVA_MXN --------------!!!!!!!!!!!!!!!!!!! cambio 
,SUM(IVA_IMPUESTO_ME) AS Impuesto_IVA_ME
,SUM(IMPUESTO_IVA_VALUACION) AS Impuesto_IVA_Val_Mon
,CTA_CONTABLE_IVA AS Cuenta_contable_IVA
,cast(SUM(IEPS_IMPUESTO_MXN)  as decimal(18,2)) AS Impuesto_IEPS_MXN --------------!!!!!!!!!!!!!!!!!!! cambio 
,SUM(IEPS_IMPUESTO_ME) AS Impuesto_IEPS_ME
,SUM(IMPUESTO_IEPS_VALMON) AS Impuesto_IEPS_Val_Mon
,CASE WHEN IEPS_IMPUESTO_MXN IS NULL 
      THEN NULL 
      ELSE CASE WHEN upper({p_tipo_reporte}) = 'PAGADO' AND POLO.PAGADA2 IN ('PT', 'PP') AND POLO.ESTADO IN ('CLEARED', 'Nota de Credito', 'Factura') 
                THEN COMB_CONT_COBRO_IEPS 
                ELSE CTA_CONTABLE_IEPS END 
END AS Cuenta_contable_IEPS
,cast(sum(RET_IVA_IMPUESTO_MXN) as decimal(18,2))  AS Retencin_IVA_MXN --------------!!!!!!!!!!!!!!!!!!! cambio 
,RET_IVA_IMPUESTO_ME AS Retencin_IVA_ME
,RETENCION_IVA_VALMON AS Retencin_IVA_Val_Mon
,CTA_CONTABLE_RET_IVA AS Cuenta_contable_ret_IVA
,sum(RET_ISR_IMPUESTO_MXN) AS Retencin_ISR_MXN
,RET_ISR_IMPUESTO_ME AS Retencin_ISR_ME
,RETENCION_ISR_VALMON AS Retencin_ISR_Val_Mon
,CTA_CONTABLE_RET_ISR AS Cuenta_contable_ret_ISR
,NUMERO_COBRO AS Nmero_cobro
,REF_PAGO_ESTRUCT AS Referencia_pago_estructurada
,ESTADO AS Estado
,FECHA_COBRO AS Fecha_cobro
,FECHA_CTABLE_DEP AS Fecha_contable2
,FECHA_COBRO_DEPOSITO AS Fecha_depsito
,FECHA_REVERSA AS FECHA_REVERSA
,MONEDA_COBRO AS Moneda2
,FECHA_TIPO_CAMBIO AS Fecha_cambio2
,CLASE_TIPO_CAMBIO AS Clase_tipo_cambio2
,TIPO_CAMBIO AS Tipo_cambio2

,CASE WHEN upper({p_tipo_reporte}) = 'REVERTIDO' AND POLO.PAGADA2 IN ('NP', 'PP', 'PT') AND POLO.ESTADO IN ('REVERSED')
  THEN CASE WHEN IMPORTE_APLICADO_MXN > 0 /*VALIDA LINEA BASE DE PAGO*/
      THEN IMPORTE_COBRO_MXN /*SI ES LINEA BASE SE MANTIENE IGUAL*/
            ELSE CASE WHEN IMPORTE_COBRO_MXN IS NOT NULL AND IMPORTE_COBRO_MXN != 0 
            THEN IMPORTE_COBRO_MXN * -1 
                      ELSE IMPORTE_COBRO_MXN 
                 END
         END
    ELSE IMPORTE_COBRO_MXN
END AS Importe_MXN2




,CASE WHEN upper({p_tipo_reporte}) = 'REVERTIDO' AND POLO.PAGADA2 IN ('NP', 'PP', 'PT') AND POLO.ESTADO IN ('REVERSED')
  THEN CASE WHEN IMPORTE_APLICADO_MXN > 0 /*VALIDA LINEA BASE DE PAGO*/
      THEN IMPORTE_COBRO_ME /*SI ES LINEA BASE SE MANTIENE IGUAL*/
            ELSE CASE WHEN IMPORTE_COBRO_ME IS NOT NULL AND IMPORTE_COBRO_ME != 0 
            THEN IMPORTE_COBRO_ME * -1 
                      ELSE IMPORTE_COBRO_ME 
                 END
         END
    ELSE IMPORTE_COBRO_ME
END AS Importe_ME2
,IMPORTE_APLICADO_MXN AS Importe_Aplicado_MXN
,IMPORTE_APLICADO_ME AS Importe_Aplicado_ME
,BANK_NAME AS Banco_remesa
,BANK_ACCOUNT_NAME AS Cuenta
,COBRO_CFDI AS Uso_CFDI2
,INFORMACION_REG AS Informacin_Regional
,COMBRO_IMP_ID_UNICO as Cobro_Impuestos_IDunico

FROM (
        select 
                RACUSTOMERTRXORGID,
                CUSTOMER_TRX_ID_RA,
                NUMERO_TRANSACCION,
                NUMERO_LINEA_TRANSACCION,
                RABATCHBATCHSOURCESEQID,
                CLASE_TRANSACCION,
                COMPLETADA,
                PAGADA2,
                ACREDITADA,
                IMPRESA,
                ANULAR,
                TIPO_TRANSACCION,
                RACUSTOMERTRXBILLTOCUSTOMERID,
                CASE WHEN TIPO_TRANSACCION like 'NC%' AND IMPORTE_MX > 0 THEN IMPORTE_MX * -1 ELSE IMPORTE_MX END IMPORTE_MX,
                CASE WHEN TIPO_TRANSACCION like 'NC%' AND IMPORTE_ME > 0 THEN IMPORTE_ME * -1 ELSE IMPORTE_ME END IMPORTE_ME,
                MONEDA_RA,
                FECHA_TC_TRX,
                CLASE_TC_TRX,
                TC_TRX,
                FECHA_TRANSACCION,
                FECHA_CONTABLE,
                VALOR_CONTEXTO,
                USO_CFDI,
                METODO_PAGO,
                FORMAS_PAGO,
                TIPO_RELACION,
                UUID_RELACIONADO,
                ARTICULO,
                DESCRIPCION_ARTICULO,
                UNIDAD_MEDIDA,
                CLASIFICACION_IMPUESTOS,
                CLASIF_IVA_RET,
                CLASIF_ISR_RET,
                --CASE WHEN CLASE_TRANSACCION like 'Nota de crédito' AND INGRESO_MX > 0 THEN INGRESO_MX * -1 ELSE INGRESO_MX END  INGRESO_MX,
                 --CASE WHEN (CLASS_IMP_IVA LIKE 'MX_IVA0%' OR CLASS_IMP_IVA LIKE 'MX_IVA_0%') AND CTA_CONTABLE_IEPS IS NOT NULL 
                  --THEN 0
                  --ELSE CASE WHEN (CLASS_IMP_IVA LIKE 'MX_IVA0%' OR CLASS_IMP_IVA LIKE 'MX_IVA_0%') AND CTA_CONTABLE_IEPS IS NULL
                    --THEN SUM_INGRESO_MXN
                    --ELSE 
                    (CASE WHEN CLASE_TRANSACCION like 'Nota de crédito' AND INGRESO_MX > 0 
                          THEN    INGRESO_MX * -1 
                          ELSE    CASE WHEN CLASE_TRANSACCION like 'Nota de crédito' AND UPPER(DESCRIPCION_ARTICULO) LIKE '%DESCUENTO%'
                                        THEN decode(sign(INGRESO_MX),1,INGRESO_MX,-1,INGRESO_MX*-1,0)
                                        ELSE CASE WHEN CLASE_TRANSACCION not like 'Nota de crédito' AND UPPER(DESCRIPCION_ARTICULO) LIKE '%DESCUENTO%'
                                                    THEN decode(sign(INGRESO_MX),1,INGRESO_MX*-1,-1,INGRESO_MX,0)
                                                    ELSE INGRESO_MX 
                                             END
                                  END
                          END)
                    --END
                --END 
                INGRESO_MX,

                CASE WHEN CLASE_TRANSACCION like 'Nota de crédito' AND INGRESO_ME > 0 THEN INGRESO_ME * -1 ELSE INGRESO_ME END  INGRESO_ME,
                INGRESO_VALMON,
                --CTA_CONTABLE_INGRESO,
                --CASE WHEN (CLASS_IMP_IVA LIKE 'MX_IVA0%' OR CLASS_IMP_IVA LIKE 'MX_IVA_0%') THEN CTA_CONTABLE_INGRESO2 ELSE CTA_CONTABLE_INGRESO END CTA_CONTABLE_INGRESO,
                CTA_CONTABLE_INGRESO,

                CASE WHEN CLASE_TRANSACCION like 'Nota de crédito' AND IVA_IMPUESTO_MX > 0 THEN IVA_IMPUESTO_MX * -1 ELSE IVA_IMPUESTO_MX END IVA_IMPUESTO_MX,
                CASE WHEN CLASE_TRANSACCION like 'Nota de crédito' AND IVA_IMPUESTO_ME > 0 THEN IVA_IMPUESTO_ME * -1 ELSE IVA_IMPUESTO_ME END IVA_IMPUESTO_ME,
                IMPUESTO_IVA_VALUACION,
                CTA_CONTABLE_IVA,
                CASE WHEN CLASE_TRANSACCION like 'Nota de crédito' AND IEPS_IMPUESTO_MXN > 0 THEN IEPS_IMPUESTO_MXN * -1 ELSE IEPS_IMPUESTO_MXN END IEPS_IMPUESTO_MXN,
                --CASE WHEN (CLASS_IMP_IVA LIKE 'MX_IVA0%' OR CLASS_IMP_IVA LIKE 'MX_IVA_0%') AND CTA_CONTABLE_IEPS IS NOT NULL 
                  --THEN SUM_IMPUESTO_IEPS
                  --ELSE CASE WHEN (CLASS_IMP_IVA LIKE 'MX_IVA0%' OR CLASS_IMP_IVA LIKE 'MX_IVA_0%') AND CTA_CONTABLE_IEPS IS NULL
                    --THEN 0
                    --ELSE (CASE WHEN CLASE_TRANSACCION like 'Nota de crédito' AND IEPS_IMPUESTO_MXN > 0 THEN IEPS_IMPUESTO_MXN * -1 ELSE IEPS_IMPUESTO_MXN END)
                    --END
                --END IEPS_IMPUESTO_MXN,


                CASE WHEN CLASE_TRANSACCION like 'Nota de crédito' AND IEPS_IMPUESTO_ME > 0 THEN IEPS_IMPUESTO_ME * -1 ELSE IEPS_IMPUESTO_ME END  IEPS_IMPUESTO_ME,
                IMPUESTO_IEPS_VALMON,
                
                --CTA_CONTABLE_IEPS,
                 --CASE WHEN (CLASS_IMP_IVA LIKE 'MX_IVA0%' OR CLASS_IMP_IVA LIKE 'MX_IVA_0%') AND CTA_CONTABLE_IEPS IS NULL AND SUM_IMPUESTO_IEPS <> 0
                --THEN CTA_CONTABLE_INGRESO2 
                --ELSE CTA_CONTABLE_IEPS END CTA_CONTABLE_IEPS,
                CTA_CONTABLE_IEPS,

                CASE WHEN CLASE_TRANSACCION like 'Nota de crédito' AND RET_IVA_IMPUESTO_MXN < 0 THEN ABS(RET_IVA_IMPUESTO_MXN) ELSE RET_IVA_IMPUESTO_MXN END  RET_IVA_IMPUESTO_MXN,
                CASE WHEN CLASE_TRANSACCION like 'Nota de crédito' AND RET_IVA_IMPUESTO_ME < 0 THEN ABS(RET_IVA_IMPUESTO_ME) ELSE RET_IVA_IMPUESTO_ME END RET_IVA_IMPUESTO_ME,
                RETENCION_IVA_VALMON,
                CTA_CONTABLE_RET_IVA,
                CASE WHEN CLASE_TRANSACCION like 'Nota de crédito' AND RET_ISR_IMPUESTO_MXN < 0 THEN ABS(RET_ISR_IMPUESTO_MXN) ELSE RET_ISR_IMPUESTO_MXN END  RET_ISR_IMPUESTO_MXN,
                CASE WHEN CLASE_TRANSACCION like 'Nota de crédito' AND RET_ISR_IMPUESTO_ME < 0 THEN ABS(RET_ISR_IMPUESTO_ME) ELSE RET_ISR_IMPUESTO_ME END RET_ISR_IMPUESTO_ME,
                RETENCION_ISR_VALMON,
                CTA_CONTABLE_RET_ISR,
                RACUSTOMERTRXLINETAXCLASSIFICATIONCODE,
                NUMERO_COBRO,
                REF_PAGO_ESTRUCT,
                ESTADO,
                FECHA_COBRO,
                FECHA_CTABLE_DEP,
                FECHA_COBRO_DEPOSITO,
                FECHA_REVERSA,
                MONEDA_COBRO,
                FECHA_TIPO_CAMBIO,
                CLASE_TIPO_CAMBIO,
                TIPO_CAMBIO,
                IMPORTE_COBRO_MXN,
                IMPORTE_COBRO_ME,
                IMPORTE_APLICADO_MXN,
                IMPORTE_APLICADO_ME,
                MONTO_APLICADO_CALC,
                IMPORTE_COBRO_CUST,
                COBRO_CFDI,
                COMBRO_IMP_ID_UNICO,
                IMPORTE_MXN,
                INFORMACION_REG,
                BANK_ACCOUNT_NAME,
                BANK_NAME,
                COMB_CONT_COBRO_IVA,
                COMB_CONT_COBRO_IEPS,
                RECEIPT_NUMBER,
                AMOUNT_DUE_MXN,
                AMOUNT_DUE_ME
        from (
                select 
                      RACUSTOMERTRXORGID,
                      CUSTOMER_TRX_ID_RA,
                      NUMERO_TRANSACCION,
                      NUMERO_LINEA_TRANSACCION,
                      RABATCHBATCHSOURCESEQID,
                      CLASE_TRANSACCION,
                      COMPLETADA,
                      PAGADA2,
                      ACREDITADA,
                      IMPRESA,
                      ANULAR,
                      TIPO_TRANSACCION,
                      RACUSTOMERTRXBILLTOCUSTOMERID,
                      IMPORTE_MX,
                      IMPORTE_ME,
                      MONEDA_RA,
                      FECHA_TC_TRX,
                      CLASE_TC_TRX,
                      TC_TRX,
                      FECHA_TRANSACCION,
                      FECHA_CONTABLE,
                      VALOR_CONTEXTO,
                      USO_CFDI,
                      METODO_PAGO,
                      FORMAS_PAGO,
                      TIPO_RELACION,
                      UUID_RELACIONADO,
                      ARTICULO,
                      DESCRIPCION_ARTICULO,
                      UNIDAD_MEDIDA,
                      CLASIFICACION_IMPUESTOS,
                      CLASIF_IVA_RET,
                      (CASE WHEN RACUSTOMERTRXLINETAXCLASSIFICATIONCODE LIKE 'MX_RET_IR%' AND (TIPO_TRANSACCION = 'CM') THEN RACUSTOMERTRXLINETAXCLASSIFICATIONCODE
                          ELSE CLASIF_ISR_RET END
                      )  CLASIF_ISR_RET,
                      (CASE WHEN PAGADA2 = 'NP' THEN INGRESO_MX ELSE
                          CASE WHEN TIPO_CAMBIO IS NULL THEN ((IMPORTE_APLICADO_MXN / IMPORTE_MX) * INGRESO_MX) -------------!!!!! cambio
                             ELSE  DECODE( INGRESO_ME,0,0, (((IMPORTE_APLICADO_ME / IMPORTE_ME) * INGRESO_ME) * TIPO_CAMBIO)   ) END -------------!!!!! cambio
                       END) INGRESO_MX,
                      (CASE WHEN PAGADA2 = 'NP' THEN INGRESO_ME
                          ELSE CASE WHEN TIPO_CAMBIO IS NOT NULL THEN DECODE(INGRESO_ME,0,0,  cast(substr(((IMPORTE_APLICADO_ME / IMPORTE_ME) * INGRESO_ME), 1,INSTR(((IMPORTE_APLICADO_ME / IMPORTE_ME) * INGRESO_ME),'.')+1)  as decimal(18,2))    ) ELSE NULL END END
                      ) INGRESO_ME,
                      (CASE WHEN TIPO_CAMBIO IS NULL THEN NULL
                          ELSE  DECODE(INGRESO_ME,0,0,cast(substr(((((IMPORTE_APLICADO_ME / IMPORTE_ME) * INGRESO_ME) * TC_TRX) - (((IMPORTE_APLICADO_ME / IMPORTE_ME) * INGRESO_ME) * TIPO_CAMBIO)), 1,instr(((((IMPORTE_APLICADO_ME / IMPORTE_ME) * INGRESO_ME) * TC_TRX) - (((IMPORTE_APLICADO_ME / IMPORTE_ME) * INGRESO_ME) * TIPO_CAMBIO)),'.')+1)  as decimal(18,2))    ) END
                      ) INGRESO_VALMON,
                      (CASE WHEN INGRESO_MX IS NULL AND INGRESO_ME IS NULL AND (TIPO_TRANSACCION = 'CM') THEN NULL
                              ELSE CTA_CONTABLE_INGRESO END
                      ) CTA_CONTABLE_INGRESO,
                      (CASE WHEN PAGADA2 = 'NP' THEN IVA_IMPUESTO_MX ELSE
                          CASE WHEN TIPO_CAMBIO IS NULL THEN ((IMPORTE_APLICADO_MXN / IMPORTE_MX) * IVA_IMPUESTO_MX) --------------!!!!!!!!!!!!!!!!!!! cambio 
                             ELSE  DECODE(INGRESO_ME,0,0,(((IMPORTE_APLICADO_ME / IMPORTE_ME) * IVA_IMPUESTO_ME) * TIPO_CAMBIO)) END --------------!!!!!!!!!!!!!!!!!!! cambio 
                       END) IVA_IMPUESTO_MX,
                      (CASE WHEN PAGADA2 = 'NP' THEN IVA_IMPUESTO_ME ELSE CASE WHEN TIPO_CAMBIO IS NOT NULL 
                            THEN DECODE(INGRESO_ME,0,0,cast(substr(((IMPORTE_APLICADO_ME / IMPORTE_ME) * IVA_IMPUESTO_ME), 1, instr(((IMPORTE_APLICADO_ME / IMPORTE_ME) * IVA_IMPUESTO_ME),'.')+1)   as decimal(18,2))     ) ELSE NULL END END) IVA_IMPUESTO_ME,
                      (CASE WHEN TIPO_CAMBIO IS NULL THEN NULL
                          ELSE  DECODE(INGRESO_ME,0,0,cast(substr(((((IMPORTE_APLICADO_ME / IMPORTE_ME) * IVA_IMPUESTO_ME) * TC_TRX) - (((IMPORTE_APLICADO_ME / IMPORTE_ME) * IVA_IMPUESTO_ME) * TIPO_CAMBIO)), 1, instr(((((IMPORTE_APLICADO_ME / IMPORTE_ME) * IVA_IMPUESTO_ME) * TC_TRX) - (((IMPORTE_APLICADO_ME / IMPORTE_ME) * IVA_IMPUESTO_ME) * TIPO_CAMBIO)),'.')+1)   as decimal(18,2))   ) END
                       ) IMPUESTO_IVA_VALUACION,
                      (CASE WHEN PAGADA2 = 'NP' THEN CTA_CONTABLE_IVA
                          ELSE NVL(COMB_CONT_COBRO_IVA, CTA_CONTABLE_IVA) END
                      ) CTA_CONTABLE_IVA,
                      (CASE WHEN PAGADA2 = 'NP' THEN IEPS_IMPUESTO_MXN
                          ELSE CASE WHEN TIPO_CAMBIO IS NULL THEN ((IMPORTE_APLICADO_MXN / IMPORTE_MX) * IEPS_IMPUESTO_MXN) --------------!!!!!!!!!!!!!!!!!!! cambio 
                                ELSE  DECODE(INGRESO_ME,0,0,(((IMPORTE_APLICADO_ME / IMPORTE_ME) * IEPS_IMPUESTO_ME) * TIPO_CAMBIO) ) END END --------------!!!!!!!!!!!!!!!!!!! cambio 
                      ) IEPS_IMPUESTO_MXN,
                      (CASE WHEN PAGADA2 = 'NP' THEN IEPS_IMPUESTO_ME
                          ELSE CASE WHEN TIPO_CAMBIO IS NOT NULL THEN DECODE(INGRESO_ME,0,0,cast(substr(((IMPORTE_APLICADO_ME / IMPORTE_ME) * IEPS_IMPUESTO_ME), 1,instr(((IMPORTE_APLICADO_ME / IMPORTE_ME) * IEPS_IMPUESTO_ME),'.')+1)  as decimal(18,2))    ) ELSE NULL END END
                      ) IEPS_IMPUESTO_ME,
                      (CASE WHEN TIPO_CAMBIO IS NULL THEN NULL
                          ELSE  DECODE(INGRESO_ME,0,0,cast(substr(((((IMPORTE_APLICADO_ME / IMPORTE_ME) * IEPS_IMPUESTO_ME) * TC_TRX) - (((IMPORTE_APLICADO_ME / IMPORTE_ME) * IEPS_IMPUESTO_ME) * TIPO_CAMBIO)), 1,instr(((((IMPORTE_APLICADO_ME / IMPORTE_ME) * IEPS_IMPUESTO_ME) * TC_TRX) - (((IMPORTE_APLICADO_ME / IMPORTE_ME) * IEPS_IMPUESTO_ME) * TIPO_CAMBIO)),'.')+1)  as decimal(18,2))   ) END
                      ) IMPUESTO_IEPS_VALMON,
                      (CASE WHEN PAGADA2 = 'NP' THEN CTA_CONTABLE_IEPS
                          WHEN CTA_CONTABLE_IEPS <> '0' AND (PAGADA2 = 'PT' OR PAGADA2 = 'PP') THEN COMB_CONT_COBRO_IEPS
                          ELSE CTA_CONTABLE_IEPS END
                      ) CTA_CONTABLE_IEPS,
                      (CASE WHEN PAGADA2 = 'NP' THEN RET_IVA_IMPUESTO_MXN ELSE
                          CASE WHEN TIPO_CAMBIO IS NULL THEN ((IMPORTE_APLICADO_MXN / IMPORTE_MX) * RET_IVA_IMPUESTO_MXN)     --------------!!!!!!!!!!!!!!!!!!! cambio 
                               ELSE  DECODE(INGRESO_ME,0,0,(((IMPORTE_APLICADO_ME / IMPORTE_ME) * RET_IVA_IMPUESTO_ME) * TIPO_CAMBIO) ) END END --------------!!!!!!!!!!!!!!!!!!! cambio 
                      ) RET_IVA_IMPUESTO_MXN,
                      (CASE WHEN PAGADA2 = 'NP' THEN RET_IVA_IMPUESTO_ME
                          ELSE CASE WHEN TIPO_CAMBIO IS NOT NULL THEN  DECODE(INGRESO_ME,0,0,cast(substr(((IMPORTE_APLICADO_ME / IMPORTE_ME) * RET_IVA_IMPUESTO_ME), 1,instr(((IMPORTE_APLICADO_ME / IMPORTE_ME) * RET_IVA_IMPUESTO_ME),'.')+1) as decimal(18,2))  ) ELSE NULL END END
                      ) RET_IVA_IMPUESTO_ME,
                      (CASE WHEN TIPO_CAMBIO IS NULL THEN NULL
                          ELSE  DECODE(INGRESO_ME,0,0,cast(substr(((((IMPORTE_APLICADO_ME / IMPORTE_ME) * RET_IVA_IMPUESTO_ME) * TC_TRX) - (((IMPORTE_APLICADO_ME / IMPORTE_ME) * RET_IVA_IMPUESTO_ME) * TIPO_CAMBIO)), 1,instr(((((IMPORTE_APLICADO_ME / IMPORTE_ME) * RET_IVA_IMPUESTO_ME) * TC_TRX) - (((IMPORTE_APLICADO_ME / IMPORTE_ME) * RET_IVA_IMPUESTO_ME) * TIPO_CAMBIO)),'.')+1) as decimal(18,2))   ) END
                      ) RETENCION_IVA_VALMON,
                      CTA_CONTABLE_RET_IVA,
                      (CASE WHEN RACUSTOMERTRXLINETAXCLASSIFICATIONCODE LIKE 'MX_RET_IR%' AND (TIPO_TRANSACCION = 'CM') THEN IMPORTE_MX
                          ELSE CASE WHEN PAGADA2 = 'NP' THEN RET_ISR_IMPUESTO_MXN
                                ELSE CASE WHEN TIPO_CAMBIO IS NULL THEN cast(substr(((IMPORTE_APLICADO_MXN / IMPORTE_MX) * RET_ISR_IMPUESTO_MXN), 1,instr(((IMPORTE_APLICADO_MXN / IMPORTE_MX) * RET_ISR_IMPUESTO_MXN),'.')+1)  as decimal(18,2))
                                      ELSE  DECODE(INGRESO_ME,0,0,cast(substr((((IMPORTE_APLICADO_ME / IMPORTE_ME) * RET_ISR_IMPUESTO_ME) * TIPO_CAMBIO), 1,instr((((IMPORTE_APLICADO_ME / IMPORTE_ME) * RET_ISR_IMPUESTO_ME) * TIPO_CAMBIO),'.')+1)  as decimal(18,2))   )
                                END
                               END
                      END) RET_ISR_IMPUESTO_MXN,
                      (CASE WHEN RACUSTOMERTRXLINETAXCLASSIFICATIONCODE LIKE 'MX_RET_IR%' AND (TIPO_TRANSACCION = 'CM') THEN IMPORTE_ME
                          ELSE CASE WHEN PAGADA2 = 'NP' THEN RET_ISR_IMPUESTO_ME
                                ELSE CASE WHEN TIPO_CAMBIO IS NOT NULL THEN  DECODE(INGRESO_ME,0,0,cast(substr(((IMPORTE_APLICADO_ME / IMPORTE_ME) * RET_ISR_IMPUESTO_ME), 1,instr(((IMPORTE_APLICADO_ME / IMPORTE_ME) * RET_ISR_IMPUESTO_ME),'.')+1)  as decimal(18,2))   ) ELSE NULL END END
                       END ) RET_ISR_IMPUESTO_ME,
                      (CASE WHEN RACUSTOMERTRXLINETAXCLASSIFICATIONCODE LIKE 'MX_RET_IR%' AND (TIPO_TRANSACCION = 'CM') AND FECHA_TC_TRX IS NOT NULL THEN cast(substr(((IMPORTE_ME * TC_TRX) - (IMPORTE_ME * TC_TRX)), 1, instr(((IMPORTE_ME * TC_TRX) - (IMPORTE_ME * TC_TRX)),'.')+1) as decimal(18,2))
                          ELSE CASE WHEN TIPO_CAMBIO IS NULL THEN NULL
                                 ELSE  DECODE(INGRESO_ME,0,0,cast(substr(((((IMPORTE_APLICADO_ME / IMPORTE_ME) * RET_ISR_IMPUESTO_ME) * TC_TRX) - (((IMPORTE_APLICADO_ME / IMPORTE_ME) * RET_ISR_IMPUESTO_ME) * TIPO_CAMBIO)), 1,instr(((((IMPORTE_APLICADO_ME / IMPORTE_ME) * RET_ISR_IMPUESTO_ME) * TC_TRX) - (((IMPORTE_APLICADO_ME / IMPORTE_ME) * RET_ISR_IMPUESTO_ME) * TIPO_CAMBIO)),'.')+1)   as decimal(18,2))   ) END
                       END ) RETENCION_ISR_VALMON,
                      (CASE WHEN RACUSTOMERTRXLINETAXCLASSIFICATIONCODE LIKE 'MX_RET_IR%' AND (TIPO_TRANSACCION = 'CM') THEN CTA_CONTABLE_INGRESO
                          ELSE CTA_CONTABLE_RET_ISR END
                      ) CTA_CONTABLE_RET_ISR,
                      RACUSTOMERTRXLINETAXCLASSIFICATIONCODE,
                      NUMERO_COBRO,
                      REF_PAGO_ESTRUCT,
                      ESTADO,
                      FECHA_COBRO,
                      FECHA_CTABLE_DEP,
                      FECHA_COBRO_DEPOSITO,
                      FECHA_REVERSA,
                      MONEDA_COBRO,
                      FECHA_TIPO_CAMBIO,
                      CLASE_TIPO_CAMBIO,
                      TIPO_CAMBIO,
                      IMPORTE_COBRO_MXN,
                      IMPORTE_COBRO_ME,
                      IMPORTE_APLICADO_MXN,
                      IMPORTE_APLICADO_ME,
                      MONTO_APLICADO_CALC,
                      IMPORTE_COBRO_CUST,
                      COBRO_CFDI,
                      COMBRO_IMP_ID_UNICO,
                      IMPORTE_MXN,
                      INFORMACION_REG,
                      BANK_ACCOUNT_NAME,
                      BANK_NAME,
                      COMB_CONT_COBRO_IVA,
                      COMB_CONT_COBRO_IEPS,
                      RECEIPT_NUMBER,
                      AMOUNT_DUE_MXN,
                      AMOUNT_DUE_ME
                from (
                        select /*+ NO_MERGE(FACTURAS) NO_MERGE(COBROS)  */ 
                              RACUSTOMERTRXORGID,
                              CUSTOMER_TRX_ID_RA,
                              NUMERO_TRANSACCION,
                              NUMERO_LINEA_TRANSACCION,
                              RABATCHBATCHSOURCESEQID,
                              CLASE_TRANSACCION,
                              COMPLETADA,
                              PAGADA2,
                              ACREDITADA,
                              IMPRESA,
                              ANULAR,
                              TIPO_TRANSACCION,
                              RACUSTOMERTRXBILLTOCUSTOMERID,
                              IMPORTE_MX,
                              IMPORTE_ME,
                              MONEDA_RA,
                              FECHA_TC_TRX,
                              CLASE_TC_TRX,
                              TC_TRX,
                              FECHA_TRANSACCION,
                              FECHA_CONTABLE,
                              VALOR_CONTEXTO,
                              USO_CFDI,
                              METODO_PAGO,
                              FORMAS_PAGO,
                              TIPO_RELACION,
                              UUID_RELACIONADO,
                              ARTICULO,
                              DESCRIPCION_ARTICULO,
                              UNIDAD_MEDIDA,
                              CLASIFICACION_IMPUESTOS,
                              CLASIF_IVA_RET,
                              CLASIF_ISR_RET,
                              INGRESO_MX,
                              INGRESO_ME,
                              CTA_CONTABLE_INGRESO,
                              IVA_IMPUESTO_MX,
                              IVA_IMPUESTO_ME,
                              CTA_CONTABLE_IVA,
                              IEPS_IMPUESTO_MXN,
                              IEPS_IMPUESTO_ME,
                              CTA_CONTABLE_IEPS,
                              RET_IVA_IMPUESTO_MXN,
                              RET_IVA_IMPUESTO_ME,
                              CTA_CONTABLE_RET_IVA,
                              RET_ISR_IMPUESTO_MXN,
                              RET_ISR_IMPUESTO_ME,
                              CTA_CONTABLE_RET_ISR,
                              RACUSTOMERTRXLINETAXCLASSIFICATIONCODE,
                              CASE WHEN CLASE_TRANSACCION like 'Nota de crédito' THEN NVL(CMFACT.RACUSTOMERTRXTRXNUMBER,NUMERO_COBRO) ELSE NUMERO_COBRO END NUMERO_COBRO,
                              CASE WHEN CLASE_TRANSACCION like 'Nota de crédito' THEN NVL(CMFACT.ESTATUS,ESTADO) ELSE ESTADO END ESTADO,
                              CASE WHEN CLASE_TRANSACCION like 'Nota de crédito' THEN NVL(CMFACT.ARRECEIVABLEAPPLICATIONAPPLYDATE,FECHA_COBRO) ELSE FECHA_COBRO END FECHA_COBRO,
                              CASE WHEN CLASE_TRANSACCION like 'Nota de crédito' THEN NVL(CMFACT.ARRECEIVABLEAPPLICATIONAPPLYDATE,FECHA_CTABLE_DEP) ELSE FECHA_CTABLE_DEP END  FECHA_CTABLE_DEP,
                              FECHA_COBRO_DEPOSITO,
                              FECHA_REVERSA,
                              CASE WHEN CLASE_TRANSACCION like 'Nota de crédito' AND PAGADA2 != 'NP' THEN NVL(MONEDA_RA, MONEDA_COBRO) ELSE MONEDA_COBRO END MONEDA_COBRO,
                              CASE WHEN CLASE_TRANSACCION like 'Nota de crédito' AND PAGADA2 != 'NP' AND RECEIPT_NUMBER IS NULL THEN FECHA_TC_TRX ELSE FECHA_TIPO_CAMBIO END FECHA_TIPO_CAMBIO,
                              CASE WHEN CLASE_TRANSACCION like 'Nota de crédito' AND PAGADA2 != 'NP' AND RECEIPT_NUMBER IS NULL THEN CLASE_TC_TRX ELSE CLASE_TIPO_CAMBIO END CLASE_TIPO_CAMBIO,
                              CASE WHEN CLASE_TRANSACCION like 'Nota de crédito' AND PAGADA2 != 'NP' AND RECEIPT_NUMBER IS NULL THEN TC_TRX ELSE TIPO_CAMBIO END TIPO_CAMBIO,
                              CASE WHEN CLASE_TRANSACCION like 'Nota de crédito' THEN NVL(CMFACT.ARRECEIVABLEAPPLICATIONAMOUNTAPPLIED,IMPORTE_COBRO_MXN)*NVL(TC_TRX,1) ELSE IMPORTE_COBRO_MXN END IMPORTE_COBRO_MXN,
                              CASE WHEN CLASE_TRANSACCION like 'Nota de crédito' THEN CASE WHEN TC_TRX IS NOT NULL THEN NVL(CMFACT.ARRECEIVABLEAPPLICATIONAMOUNTAPPLIED,IMPORTE_COBRO_ME) ELSE NULL END ELSE IMPORTE_COBRO_ME END IMPORTE_COBRO_ME,
                              CASE WHEN CLASE_TRANSACCION like 'Nota de crédito' THEN NVL(CMFACT.ARRECEIVABLEAPPLICATIONAMOUNTAPPLIED,IMPORTE_APLICADO_MXN)*NVL(TC_TRX,1) ELSE IMPORTE_APLICADO_MXN END IMPORTE_APLICADO_MXN,
                              CASE WHEN CLASE_TRANSACCION like 'Nota de crédito' THEN CASE WHEN TC_TRX IS NOT NULL THEN NVL(CMFACT.ARRECEIVABLEAPPLICATIONAMOUNTAPPLIED,IMPORTE_APLICADO_ME) ELSE NULL END ELSE IMPORTE_APLICADO_ME END IMPORTE_APLICADO_ME,
                              MONTO_APLICADO_CALC,
                              IMPORTE_COBRO_CUST,
                              COBRO_CFDI,
                              COMBRO_IMP_ID_UNICO,
                              CASH_RECEIPT_ID,
                              RECEIPT_METHOD_ID,
                              IMPORTE_MXN,
                              RCPT_EXCHG_RATE,
                              RCPT_ID,
                              BANK_ACCOUNT_NAME,
                              RCPT_PAYMENT_TRXN_EXTENSION_ID,
                              PAYMENT_NUMBER,
                              TRX_NUMBER_CO,
                              REF_PAGO_ESTRUCT,
                              INFORMACION_REG,
                              BANK_NAME,
                              COMB_CONT_COBRO_IVA,
                              COMB_CONT_COBRO_IEPS,
                              RECEIPT_NUMBER,
                              AMOUNT_DUE_MXN,
                              AMOUNT_DUE_ME
                        from FACTURAS
                        left join COBROS
                          on FACTURAS.CUSTOMER_TRX_ID_RA = COBROS.CUSTOMER_TRX_ID_CO

                          and (case when CLASIFICACION_IMPUESTOS like '%IVA16%' then cobros.CodeCombinationSegment6 = '121000000'  -------------------------!!!!!!!!!!!!!!!!
                                    when CLASIFICACION_IMPUESTOS like '%IVA0%' then cobros.CodeCombinationSegment6 = '101000000' 
                                    when DESCRIPCION_ARTICULO like '%DESCUENTO_PROMOCION%' then cobros.CodeCombinationSegment6 = '101000000' -------------------------!!!!!!!!!!!!!!!!03112025
                                    else 1=1 end )
                          /*and (case when IEPS_IMPUESTO_MXN is not null then COBROS.CodeCombinationSegment6_ieps = '100031100' 
                                    when IEPS_IMPUESTO_MXN is null and COBROS.CodeCombinationSegment6_ieps is not null then cobros.CodeCombinationSegment6_ieps = '100030100' else 1=1 end)*/

                        left join CMFACT
                          on FACTURAS.CUSTOMER_TRX_ID_RA = CMFACT.ARRECEIVABLEAPPLICATIONCUSTOMERTRXID
                        where 1=1
                        --and  FACTURAS.CUSTOMER_TRX_ID_RA   in ( 80151476)
                        --and  FACTURAS.VALOR_CONTEXTO  = 'México'
                      )             
              )ORIGINAL--MPRR
              /*LEFT JOIN AJUSTE_COBROS_NOTAS AJUSTE
              ON AJUSTE.NUMERO_COBRO_2= ORIGINAL.NUMERO_COBRO
              AND AJUSTE.CLASS_IMP_IVA=ORIGINAL.CLASIFICACION_IMPUESTOS
            */
        union all
        select
              RACUSTOMERTRXORGID,
              CUSTOMER_TRX_ID_RA,
              NUMERO_TRANSACCION,
              NUMERO_LINEA_TRANSACCION,
              RABATCHBATCHSOURCESEQID,
              CLASE_TRANSACCION,
              COMPLETADA,
              PAGADA2,
              ACREDITADA,
              IMPRESA,
              ANULAR,
              TIPO_TRANSACCION,
              RACUSTOMERTRXBILLTOCUSTOMERID,
              IMPORTE_MX,
              IMPORTE_ME,
              MONEDA_RA,
              FECHA_TC_TRX,
              CLASE_TC_TRX,
              TC_TRX,
              FECHA_TRANSACCION,
              FECHA_CONTABLE,
              VALOR_CONTEXTO,
              USO_CFDI,
              METODO_PAGO,
              FORMAS_PAGO,
              TIPO_RELACION, 
              UUID_RELACIONADO,
              ARTICULO,
              DESCRIPCION_ARTICULO,
              UNIDAD_MEDIDA,
              CLASIFICACION_IMPUESTOS,
              CLASIF_IVA_RET,
              CLASIF_ISR_RET,
              ((INGRESO_MX / IMPORTE_MX) * AMOUNT_DUE_MXN)  INGRESO_MX,    --------------!!!!!!!!!!!!!!!!!!! cambio 
              CASE WHEN TC_TRX IS NOT NULL THEN cast(substr(((INGRESO_ME / IMPORTE_ME) * AMOUNT_DUE_ME), 1,instr(((INGRESO_ME / IMPORTE_ME) * AMOUNT_DUE_ME),'.')+1) as decimal(18,2)) ELSE NULL END INGRESO_ME,
              NULL,
              CTA_CONTABLE_INGRESO,
              ((IVA_IMPUESTO_MX / IMPORTE_MX) * AMOUNT_DUE_MXN) IVA_IMPUESTO_MX, --------------!!!!!!!!!!!!!!!!!!! cambio 
              CASE WHEN TC_TRX IS NOT NULL THEN cast(substr(((IVA_IMPUESTO_ME / IMPORTE_ME) * AMOUNT_DUE_ME), 1,instr(((IVA_IMPUESTO_ME / IMPORTE_ME) * AMOUNT_DUE_ME),'.')+1)   as decimal(18,2))  ELSE NULL END IVA_IMPUESTO_ME,
              NULL,
              CTA_CONTABLE_IVA,
              ((IEPS_IMPUESTO_MXN / IMPORTE_MX) * AMOUNT_DUE_MXN) IEPS_IMPUESTO_MXN, --------------!!!!!!!!!!!!!!!!!!! cambio 
              CASE WHEN TC_TRX IS NOT NULL THEN cast(substr(((IEPS_IMPUESTO_ME / IMPORTE_ME) * AMOUNT_DUE_ME), 1,instr(((IEPS_IMPUESTO_ME / IMPORTE_ME) * AMOUNT_DUE_ME),'.')+1)  as decimal(18,2))  ELSE NULL END IEPS_IMPUESTO_ME,
              NULL,
              CTA_CONTABLE_IEPS,
              ((RET_IVA_IMPUESTO_MXN / IMPORTE_MX) * AMOUNT_DUE_MXN)   RET_IVA_IMPUESTO_MXN, --------------!!!!!!!!!!!!!!!!!!! cambio 
              CASE WHEN TC_TRX IS NOT NULL THEN cast(substr(((RET_IVA_IMPUESTO_ME / IMPORTE_ME) * AMOUNT_DUE_ME), 1,instr(((RET_IVA_IMPUESTO_ME / IMPORTE_ME) * AMOUNT_DUE_ME),'.')+1)  as decimal(18,2))  ELSE NULL END RET_IVA_IMPUESTO_ME,
              NULL,
              CTA_CONTABLE_RET_IVA,
              cast(substr(((RET_ISR_IMPUESTO_MXN / IMPORTE_MX) * AMOUNT_DUE_MXN), 1,instr(((RET_ISR_IMPUESTO_MXN / IMPORTE_MX) * AMOUNT_DUE_MXN),'.')+1)   as decimal(18,2))  RET_ISR_IMPUESTO_MXN,
              CASE WHEN TC_TRX IS NOT NULL THEN cast(substr(((RET_ISR_IMPUESTO_ME / IMPORTE_ME) * AMOUNT_DUE_ME), 1,instr(((RET_ISR_IMPUESTO_ME / IMPORTE_ME) * AMOUNT_DUE_ME),'.')+1)   as decimal(18,2))  ELSE NULL END  RET_ISR_IMPUESTO_ME,
              NULL,
              CTA_CONTABLE_RET_ISR,
              RACUSTOMERTRXLINETAXCLASSIFICATIONCODE,
              NULL,
              NULL,
              NULL,
              NULL,
              NULL,
              NULL,
              NULL,
              NULL,
              NULL,
              NULL,
              NULL,
              NULL,
              NULL,
              NULL,
              NULL,
              NULL,
              NULL,
              NULL,
              NULL,
              NULL,
              NULL,
              NULL,
              NULL,
              NULL,
              NULL,
              NULL,
              NULL,
              NULL
              FROM  FACTURAS FA
              WHERE 1 = 1
              AND   FA.PAGADA2 = 'PP'
      ) POLO 
INNER JOIN (SAWITH1 D2 inner join SAWITH2 D3 On D2.c2 = D3.c4) 
    ON POLO.RACUSTOMERTRXORGID = D2.c1
INNER JOIN (SAWITH3 D4 inner join SAWITH4 D5 On D4.c3 = D5.c2)
      ON POLO.RACUSTOMERTRXBILLTOCUSTOMERID = D4.c2
INNER JOIN SAWITH5  
      ON POLO.RABATCHBATCHSOURCESEQID = SAWITH5.c2

WHERE 1=1
  --TIPO DE REPORTE
  AND (CASE 
        WHEN upper({p_tipo_reporte}) = 'PAGADO'    AND POLO.PAGADA2 IN ('PT', 'PP')       AND POLO.ESTADO IN ('CLEARED', 'Nota de Credito', 'Factura') THEN 1
        WHEN upper({p_tipo_reporte}) = 'PENDIENTE' AND POLO.PAGADA2 IN ('NP', 'PP')       AND NVL(POLO.ESTADO, 'AA') NOT IN ('CLEARED', 'Nota de Credito', 'Factura','REVERSED') THEN 1
        WHEN upper({p_tipo_reporte}) = 'TODO'      AND POLO.PAGADA2 IN ('NP', 'PP', 'PT') THEN 1
        WHEN upper({p_tipo_reporte}) = 'REVERTIDO' AND POLO.PAGADA2 IN ('NP', 'PP', 'PT') AND POLO.ESTADO IN ('REVERSED') THEN 1 ELSE 0 END = 1)
  
  --NUM TRANSACCION
  --AND NVL(upper(NUMERO_TRANSACCION),'1') IN (NVL(upper({p_numero_transaccion}),NVL(upper(NUMERO_TRANSACCION),'1'))) --Comentado
  AND (upper(NUMERO_TRANSACCION) IN (DECODE(upper({p_numero_transaccion}),'TODO',UPPER(NUMERO_TRANSACCION),upper({p_numero_transaccion}))) OR NUMERO_TRANSACCION IS NULL)

   --PERIODO CONTABLE
  AND ((DECODE(date_format({p_periodo_contable_from},'yyyy-MM-dd HH24:mm:SS'),NULL,date_format('1900-01-01 00:00:00','yyyy-MM-dd HH24:mm:SS')
      ,date_format(FECHA_CONTABLE,'yyyy-MM-dd HH24:mm:SS')) 
      between NVL(date_format({p_periodo_contable_from}, 'yyyy-MM-dd HH24:mm:SS'),date_format('1900-01-01 00:00:00','yyyy-MM-dd HH24:mm:SS')) 
      and NVL(date_format({p_periodo_contable_to}, 'yyyy-MM-dd HH24:mm:SS'), date_format('1900-01-01 00:00:00','yyyy-MM-dd HH24:mm:SS'))
      ) OR FECHA_CONTABLE IS NULL)

    --PERIODO DE PAGO
  AND ((DECODE(date_format({p_periodo_pago_from},'yyyy-MM-dd HH24:mm:SS'),NULL,date_format('1900-01-01 00:00:00','yyyy-MM-dd HH24:mm:SS')
      ,date_format(FECHA_COBRO,'yyyy-MM-dd HH24:mm:SS'))
      between NVL(date_format({p_periodo_pago_from}, 'yyyy-MM-dd HH24:mm:SS'),date_format('1900-01-01 00:00:00','yyyy-MM-dd HH24:mm:SS')) 
      and NVL(date_format({p_periodo_pago_to}, 'yyyy-MM-dd HH24:mm:SS'),date_format('1900-01-01 00:00:00','yyyy-MM-dd HH24:mm:SS'))
      ) OR FECHA_COBRO IS NULL)

    --PERIODO DE TRANSACCION
     AND ((DECODE(date_format({p_fecha_transaccion_from},'yyyy-MM-dd HH24:mm:SS'),NULL,date_format('1900-01-01 00:00:00','yyyy-MM-dd HH24:mm:SS')
      ,date_format(FECHA_TRANSACCION,'yyyy-MM-dd HH24:mm:SS'))
      between NVL(date_format({p_fecha_transaccion_from}, 'yyyy-MM-dd HH24:mm:SS'),date_format('1900-01-01 00:00:00','yyyy-MM-dd HH24:mm:SS')) 
      and NVL(date_format({p_fecha_transaccion_to}, 'yyyy-MM-dd HH24:mm:SS'),date_format('1900-01-01 00:00:00','yyyy-MM-dd HH24:mm:SS'))
      ) OR FECHA_TRANSACCION IS NULL)

  --PERIODO REVERSION
    AND ((DECODE(date_format({p_fecha_reversed_d},'yyyy-MM-dd HH24:mm:SS'),NULL,date_format('1900-01-01 00:00:00','yyyy-MM-dd HH24:mm:SS')
      ,date_format(FECHA_REVERSA,'yyyy-MM-dd HH24:mm:SS'))
      between NVL(date_format({p_fecha_reversed_d}, 'yyyy-MM-dd HH24:mm:SS'),date_format('1900-01-01 00:00:00','yyyy-MM-dd HH24:mm:SS')) 
      and NVL(date_format({p_fecha_reversed_h}, 'yyyy-MM-dd HH24:mm:SS'),date_format('1900-01-01 00:00:00','yyyy-MM-dd HH24:mm:SS'))
      ) OR FECHA_REVERSA IS NULL) 
      
  --TAX CLASS
  AND ( UPPER(CLASIFICACION_IMPUESTOS) IN (DECODE(upper({p_clasificacion_impuestos}),'TODO',UPPER(CLASIFICACION_IMPUESTOS),upper({p_clasificacion_impuestos}))) OR CLASIFICACION_IMPUESTOS IS NULL)
  --TAX CLASS IVA RET
  AND ( UPPER(CLASIF_IVA_RET) IN (DECODE(upper({p_clasificacion_impuestos_iva_ret}),'TODO',UPPER(CLASIF_IVA_RET),upper({p_clasificacion_impuestos_iva_ret}))) OR CLASIF_IVA_RET IS NULL)
  --TAX CLASS ISR RET
  AND ( UPPER(CLASIF_ISR_RET) IN (DECODE(upper({p_clasificacion_impuestos_isr_ret}),'TODO',UPPER(CLASIF_ISR_RET),upper({p_clasificacion_impuestos_isr_ret}))) OR CLASIF_ISR_RET IS NULL)
  --BANCO REMESA
  AND ( UPPER(BANK_NAME) IN (DECODE(upper({p_banco_remesa}),'TODO',UPPER(BANK_NAME),upper({p_banco_remesa}))) or BANK_NAME is null)
  --BANK ACCOUNT REMESA
  AND ( UPPER(BANK_ACCOUNT_NAME) IN (DECODE(upper({p_cuenta_bancaria_remesa}),'TODO',UPPER(BANK_ACCOUNT_NAME),upper({p_cuenta_bancaria_remesa}))) or BANK_ACCOUNT_NAME is null)
  
GROUP BY 
CLASIFICACION_IMPUESTOS
,CLASIF_IVA_RET
,CLASIF_ISR_RET
,CTA_CONTABLE_INGRESO
,CTA_CONTABLE_IVA
,CASE WHEN IEPS_IMPUESTO_MXN IS NULL THEN NULL ELSE 
CASE WHEN upper({p_tipo_reporte}) = 'PAGADO' AND POLO.PAGADA2 IN ('PT', 'PP') AND POLO.ESTADO IN ('CLEARED', 'Nota de Credito', 'Factura') THEN COMB_CONT_COBRO_IEPS ELSE CTA_CONTABLE_IEPS END 
END
,CTA_CONTABLE_RET_IVA
,CTA_CONTABLE_RET_ISR
,NUMERO_COBRO
,NUMERO_TRANSACCION
,CLASE_TRANSACCION
,COMPLETADA
,PAGADA2
,ACREDITADA
,IMPRESA
,ANULAR
,TIPO_TRANSACCION
,CASE WHEN upper({p_tipo_reporte}) = 'REVERTIDO' AND POLO.PAGADA2 IN ('NP', 'PP', 'PT') AND POLO.ESTADO IN ('REVERSED')
  THEN CASE WHEN IMPORTE_APLICADO_MXN > 0 --VALIDA LINEA BASE DE PAGO
      THEN IMPORTE_MX --SI ES LINEA BASE SE MANTIENE IGUAL
            ELSE CASE WHEN IMPORTE_MX IS NOT NULL AND IMPORTE_MX != 0 
            THEN IMPORTE_MX * -1 
                      ELSE IMPORTE_MX 
                 END
         END
          
    ELSE IMPORTE_MX 
END 
,CASE WHEN upper({p_tipo_reporte}) = 'REVERTIDO' AND POLO.PAGADA2 IN ('NP', 'PP', 'PT') AND POLO.ESTADO IN ('REVERSED')
  THEN CASE WHEN IMPORTE_APLICADO_MXN > 0 --VALIDA LINEA BASE DE PAGO
      THEN IMPORTE_ME --SI ES LINEA BASE SE MANTIENE IGUAL
            ELSE CASE WHEN IMPORTE_ME IS NOT NULL AND IMPORTE_ME != 0 
            THEN IMPORTE_ME * -1 
                      ELSE IMPORTE_ME 
                 END
         END
          
    ELSE IMPORTE_ME
END 
,MONEDA_RA
,FECHA_TC_TRX
,CLASE_TC_TRX
,TC_TRX
,FECHA_TRANSACCION
,FECHA_CONTABLE
,VALOR_CONTEXTO
,USO_CFDI
,METODO_PAGO
,FORMAS_PAGO
,TIPO_RELACION
,UUID_RELACIONADO
--,RET_IVA_IMPUESTO_MXN
,RET_IVA_IMPUESTO_ME
,RETENCION_IVA_VALMON
--,RET_ISR_IMPUESTO_MXN
,RET_ISR_IMPUESTO_ME
,RETENCION_ISR_VALMON
,REF_PAGO_ESTRUCT
,ESTADO
,FECHA_COBRO
,FECHA_CTABLE_DEP
,FECHA_COBRO_DEPOSITO
,FECHA_REVERSA
,MONEDA_COBRO
,FECHA_TIPO_CAMBIO
,CLASE_TIPO_CAMBIO
,TIPO_CAMBIO
,CASE WHEN upper({p_tipo_reporte}) = 'REVERTIDO' AND POLO.PAGADA2 IN ('NP', 'PP', 'PT') AND POLO.ESTADO IN ('REVERSED')
  THEN CASE WHEN IMPORTE_APLICADO_MXN > 0 --VALIDA LINEA BASE DE PAGO
      THEN IMPORTE_COBRO_MXN --SI ES LINEA BASE SE MANTIENE IGUAL
            ELSE CASE WHEN IMPORTE_COBRO_MXN IS NOT NULL AND IMPORTE_COBRO_MXN != 0 
            THEN IMPORTE_COBRO_MXN * -1 
                      ELSE IMPORTE_COBRO_MXN 
                 END
         END
          
    ELSE IMPORTE_COBRO_MXN
END 
,CASE WHEN upper({p_tipo_reporte}) = 'REVERTIDO' AND POLO.PAGADA2 IN ('NP', 'PP', 'PT') AND POLO.ESTADO IN ('REVERSED')
  THEN CASE WHEN IMPORTE_APLICADO_MXN > 0 --VALIDA LINEA BASE DE PAGO
      THEN IMPORTE_COBRO_ME --SI ES LINEA BASE SE MANTIENE IGUAL
            ELSE CASE WHEN IMPORTE_COBRO_ME IS NOT NULL AND IMPORTE_COBRO_ME != 0 
            THEN IMPORTE_COBRO_ME * -1 
                      ELSE IMPORTE_COBRO_ME 
                 END
         END
          
    ELSE IMPORTE_COBRO_ME
END
,IMPORTE_APLICADO_MXN
,IMPORTE_APLICADO_ME
,COBRO_CFDI
,COMBRO_IMP_ID_UNICO
,INFORMACION_REG
,BANK_ACCOUNT_NAME
,BANK_NAME
--,RACUSTOMERTRXORGID
--,RACUSTOMERTRXBILLTOCUSTOMERID
--,RABATCHBATCHSOURCESEQID
,SAWITH5.c1
,D4.c1
,D5.c1
,D5.c3
,D5.c4