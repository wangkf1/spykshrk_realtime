/* -----  RSTQuery.h  ----- */
#ifndef __RSTQuery_h
#define __RSTQuery_h


#include "RStarTree.h"


/* declarations */

boolean FoundRect(RSTREE R,
                  int depth,
                  typrect rectangle,
                  boolean isinsert,
                  refinfo *infoadr);

void XstsRgn(RSTREE R,
             int depth,
             typrect rectangle1,
             typrect rectangle2,
             DirQueryProc DirQuery,
             DataQueryProc DataQuery,
             boolean *found);


void RgnCnt(RSTREE R,
            int depth,
            typrect rectangle1,
            typrect rectangle2,
            DirQueryProc DirQuery,
            DataQueryProc DataQuery,
            int *keysqualifying);


void RgnQuery(RSTREE R,
              int depth,
              typrect rectangle1,
              typrect rectangle2,
              DirQueryProc DirQuery,
              DataQueryProc DataQuery,
              QueryManageProc Manage,
              void *buf,
              boolean *finish);


void All(RSTREE R,
         int depth,
         QueryManageProc Manage,
         void *buf,
         boolean *finish);


#endif /* !__RSTQuery_h */

